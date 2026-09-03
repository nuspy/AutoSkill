"""Test fixtures: isolated SQLite database, inline jobs, in-memory events."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["AUTOSKILL_ENV"] = "test"
os.environ["AUTOSKILL_JOBS"] = "inline"
os.environ["AUTOSKILL_EVENTS"] = "memory"
os.environ["AUTOSKILL_SECRET_KEY"] = "test-secret-key-for-tests-only-0123456789"

from autoskill.config import get_settings  # noqa: E402
from autoskill.core.events import reset_event_bus  # noqa: E402
from autoskill.core.jobs import reset_job_runner  # noqa: E402
from autoskill.db.base import Base  # noqa: E402
from autoskill.db.session import get_engine, reset_engine  # noqa: E402
from autoskill.models import *  # noqa: E402,F401,F403
from autoskill.services.storage.content_store import reset_content_store  # noqa: E402


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    tmp = tempfile.mkdtemp(prefix="autoskill-test-")
    os.environ["AUTOSKILL_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp}/test.db"
    os.environ["AUTOSKILL_DATA_DIR"] = str(Path(tmp) / "data")
    get_settings.cache_clear()
    reset_engine()
    reset_event_bus()
    reset_job_runner()
    reset_content_store()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from autoskill.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    await engine.dispose()


async def register(client: AsyncClient, email: str, password: str = "password123", name: str | None = None) -> dict:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": name or email.split("@")[0]},
    )
    assert res.status_code == 201, res.text
    return res.json()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
