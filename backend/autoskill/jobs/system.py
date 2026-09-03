"""Housekeeping jobs."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete

from autoskill.core.jobs import JobContext, job
from autoskill.db.base import utcnow
from autoskill.db.session import get_session_factory
from autoskill.models.device import DeviceAuthorization
from autoskill.models.user import RefreshToken


@job("system.ping")
async def ping(ctx: JobContext, **payload) -> dict:
    await ctx.progress(50, "pinging")
    return {"pong": True, **payload}


@job("system.cleanup")
async def cleanup(ctx: JobContext, **_) -> dict:
    cutoff = utcnow() - timedelta(days=7)
    async with get_session_factory()() as session:
        r1 = await session.execute(delete(RefreshToken).where(RefreshToken.expires_at < cutoff))
        r2 = await session.execute(
            delete(DeviceAuthorization).where(DeviceAuthorization.expires_at < cutoff)
        )
        await session.commit()
    return {"refresh_tokens": r1.rowcount, "device_authorizations": r2.rowcount}
