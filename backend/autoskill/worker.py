"""arq worker entrypoint: `arq autoskill.worker.WorkerSettings`."""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron

from autoskill.config import get_settings
from autoskill.core.jobs import execute_job, get_job_runner
from autoskill.jobs import register_all_jobs


async def run_job(ctx: dict, job_id: str) -> None:
    await execute_job(job_id)


async def cron_cleanup(ctx: dict) -> None:
    await get_job_runner().enqueue("system.cleanup")


async def startup(ctx: dict) -> None:
    register_all_jobs()


class WorkerSettings:
    functions = [run_job]
    cron_jobs = [cron(cron_cleanup, hour=3, minute=15)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 8
    job_timeout = 1800
