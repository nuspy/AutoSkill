"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from autoskill import __version__
from autoskill.api.v1.router import api_router
from autoskill.config import get_settings
from autoskill.core.errors import AppError
from autoskill.jobs import register_all_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    register_all_jobs()
    yield


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
    return app


app = create_app()
