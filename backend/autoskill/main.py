"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from autoskill import __version__
from autoskill.api.dl import router as dl_router
from autoskill.api.git import router as git_router
from autoskill.api.v1.router import api_router
from autoskill.config import get_settings
from autoskill.core.errors import AppError
from autoskill.jobs import register_all_jobs
from autoskill.models import *  # noqa: F401,F403  (tables for the e2e reset)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    register_all_jobs()
    if os.environ.get("AUTOSKILL_E2E_RESET") == "1" and settings.is_sqlite:
        # end-to-end runs: start from an empty schema (SQLite file recreated by create_all)
        from autoskill.db.base import Base
        from autoskill.db.session import get_engine

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    await _resume_interrupted_work()
    yield


async def _resume_interrupted_work() -> None:
    """Pick up whatever the previous process was doing when it stopped.

    Restarts are ordinary — an autoreload after an edit, a deploy, a machine that sleeps — and until
    now they were also silent: an interview waiting on a model never came back, and the person in
    the browser went on watching a spinner for work nobody was doing.

    It runs after the end-to-end reset above, so a wiped schema has nothing to recover, and it
    refuses to take the server down with it: a failure here is logged and startup continues, because
    a server that will not start is worse than one that lost a job.
    """
    from autoskill.core.jobs import get_job_runner
    from autoskill.db.session import get_session_factory
    from autoskill.services.procedures import engine

    log = logging.getLogger(__name__)
    try:
        async with get_session_factory()() as session:
            steps = await engine.mark_interrupted(session)
        jobs = await get_job_runner().recover()
        if steps or jobs:
            log.warning("startup: resumed %d job(s), closed %d interrupted step(s)", jobs, steps)
    except Exception:  # noqa: BLE001 - recovery must never keep the server down
        log.exception("startup: could not resume interrupted work")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AutoSkill", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "Invalid request",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    app.include_router(api_router)
    app.include_router(git_router)
    app.include_router(dl_router)
    return app


app = create_app()
