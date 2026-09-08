"""SQLite has to wait for a busy database, not fail the request that reached it first.

This was a real outage in miniature: a login that writes its refresh token raced a background job
writing telemetry, one got `database is locked`, and the person saw "Something went wrong. Please try
again." — which read as an unstable backend and was only the default SQLite settings.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from autoskill.db.session import get_engine, get_session_factory


@pytest.mark.asyncio
async def test_sqlite_is_configured_to_wait_and_to_let_readers_through():
    engine = get_engine()
    if not engine.url.get_backend_name().startswith("sqlite"):
        pytest.skip("these pragmas are scoped to SQLite")
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA busy_timeout"))).scalar() >= 5000
        assert (await conn.execute(text("PRAGMA journal_mode"))).scalar().lower() in ("wal", "memory")


@pytest.mark.asyncio
async def test_concurrent_writers_do_not_raise_database_is_locked():
    """Ten commits at once used to be enough to make one fail; with a busy timeout they queue."""
    factory = get_session_factory()

    async def bump(n: int) -> None:
        async with factory() as session:
            await session.execute(
                text("CREATE TABLE IF NOT EXISTS _lock_probe (id INTEGER PRIMARY KEY, v INTEGER)")
            )
            await session.execute(text("INSERT INTO _lock_probe (v) VALUES (:v)"), {"v": n})
            await session.commit()

    try:
        await asyncio.gather(*(bump(i) for i in range(10)))
    finally:
        async with factory() as session:
            await session.execute(text("DROP TABLE IF EXISTS _lock_probe"))
            await session.commit()
