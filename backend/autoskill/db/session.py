"""Async engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from autoskill.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _prepare_sqlite(dbapi_connection, _record) -> None:
    """Make SQLite wait for a busy database instead of failing the request that hit it.

    Out of the box SQLite serialises writers with no patience: the moment two coroutines commit at
    once — a login writing its refresh token while a background job writes telemetry — one gets
    `database is locked` and the request fails, which reached the person as "Something went wrong".
    It was not the backend being unstable; it was the default settings.

    `busy_timeout` tells it to wait up to five seconds for the lock rather than give up instantly, and
    WAL lets readers run alongside the one writer instead of blocking on it — the two changes every
    SQLite-backed web app makes. They matter far less under Postgres, so they are scoped to SQLite.
    """
    cursor = dbapi_connection.cursor()
    # `busy_timeout` is the one that must always apply — it is what turns "locked, giving up now" into
    # "locked, waiting". WAL is persistent (stored in the file header), so it only has to succeed once;
    # attempting it on every connection is harmless when it is already on, but the one-time switch can
    # fail if another connection still holds the file in the old mode, and that must not break the
    # connection that hit it. So the timeout is unconditional and WAL is best-effort.
    cursor.execute("PRAGMA busy_timeout=5000")
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001, S110 - a transient lock during the one-time WAL switch is not fatal
        pass
    cursor.close()


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True}
        if settings.is_sqlite:
            kwargs = {"connect_args": {"check_same_thread": False}}
        _engine = create_async_engine(settings.database_url, **kwargs)
        if settings.is_sqlite:
            event.listen(_engine.sync_engine, "connect", _prepare_sqlite)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def reset_engine() -> None:
    """Used by tests to swap the database URL."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
