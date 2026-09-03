"""Background job runner abstraction.

Jobs are plain async functions registered by name. The inline runner executes them as
asyncio tasks in-process (dev/tests); the arq runner enqueues them on Redis for the worker.
Every job gets a `jobs` row for progress and error tracking.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from autoskill.config import get_settings
from autoskill.core.events import emit, project_channel, user_channel
from autoskill.db.base import utcnow
from autoskill.db.session import get_session_factory
from autoskill.models.job import Job

log = logging.getLogger(__name__)

JobFunc = Callable[..., Awaitable[Any]]
_registry: dict[str, JobFunc] = {}


def job(name: str) -> Callable[[JobFunc], JobFunc]:
    def decorator(func: JobFunc) -> JobFunc:
        _registry[name] = func
        return func

    return decorator


def get_job_func(name: str) -> JobFunc:
    try:
        return _registry[name]
    except KeyError as exc:
        raise KeyError(f"unknown job {name!r}") from exc


def registered_jobs() -> dict[str, JobFunc]:
    return dict(_registry)


async def _notify(job_row: Job) -> None:
    payload = {
        "job_id": job_row.id,
        "type": job_row.type,
        "status": job_row.status,
        "progress": job_row.progress,
        "message": job_row.message,
        "error": job_row.error,
    }
    if job_row.project_id:
        await emit(project_channel(job_row.project_id), "job.updated", payload)
    if job_row.user_id:
        await emit(user_channel(job_row.user_id), "job.updated", payload)


class JobContext:
    """Passed to job functions for progress reporting."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    async def progress(self, percent: int, message: str | None = None) -> None:
        async with get_session_factory()() as session:
            row = await session.get(Job, self.job_id)
            if row is None:
                return
            row.progress = max(0, min(100, percent))
            if message:
                row.message = message
            await session.commit()
            await _notify(row)


async def execute_job(job_id: str) -> None:
    """Run a job row to completion; used by both inline and arq runners."""
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(Job, job_id)
        if row is None:
            log.warning("job %s vanished", job_id)
            return
        row.status = "running"
        row.started_at = utcnow()
        await session.commit()
        job_type, payload = row.type, dict(row.payload)
        await _notify(row)

    ctx = JobContext(job_id)
    try:
        func = get_job_func(job_type)
        result = await func(ctx, **payload)
        status, error = "succeeded", None
    except Exception as exc:  # noqa: BLE001 - job failures are recorded, not raised
        log.exception("job %s (%s) failed", job_id, job_type)
        result, status, error = None, "failed", f"{exc}\n{traceback.format_exc()[-2000:]}"

    async with factory() as session:
        row = await session.get(Job, job_id)
        if row is None:
            return
        row.status = status
        row.error = error
        if isinstance(result, dict):
            row.result = result
        else:
            row.result = {"value": result} if result is not None else None
        row.progress = 100 if status == "succeeded" else row.progress
        row.finished_at = utcnow()
        await session.commit()
        await _notify(row)


class JobRunner:
    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> Job:
        payload = payload or {}
        async with get_session_factory()() as session:
            row = Job(type=job_type, payload=payload, project_id=project_id, user_id=user_id)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        await self._dispatch(row.id)
        return row

    async def _dispatch(self, job_id: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InlineJobRunner(JobRunner):
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    async def _dispatch(self, job_id: str) -> None:
        task = asyncio.create_task(execute_job(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_all(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


class ArqJobRunner(JobRunner):
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool = None

    async def _pool_or_connect(self):
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            self._pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        return self._pool

    async def _dispatch(self, job_id: str) -> None:
        pool = await self._pool_or_connect()
        await pool.enqueue_job("run_job", job_id)


_runner: JobRunner | None = None


def get_job_runner() -> JobRunner:
    global _runner
    if _runner is None:
        settings = get_settings()
        _runner = ArqJobRunner(settings.redis_url) if settings.jobs == "arq" else InlineJobRunner()
    return _runner


def reset_job_runner() -> None:
    global _runner
    _runner = None
