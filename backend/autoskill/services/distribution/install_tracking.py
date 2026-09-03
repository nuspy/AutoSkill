"""Installations: recorded on download / CLI install, confirmed by the first telemetry run."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.db.base import utcnow
from autoskill.models.hub import Installation
from autoskill.models.skill import Skill


async def record_installation(
    session: AsyncSession,
    *,
    user_id: str,
    skill_id: str,
    skill_version_id: str,
    target_agent: str,
    channel: str,
    kind: str = "permanent",
    device_id: str | None = None,
    state: str = "downloaded",
) -> Installation:
    device_key = device_id or "-"
    res = await session.execute(
        select(Installation).where(
            Installation.user_id == user_id,
            Installation.device_key == device_key,
            Installation.skill_id == skill_id,
            Installation.target_agent == target_agent,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = Installation(
            user_id=user_id,
            device_id=device_id,
            device_key=device_key,
            skill_id=skill_id,
            skill_version_id=skill_version_id,
            target_agent=target_agent,
            channel=channel,
            kind=kind,
            state=state,
        )
        session.add(row)
    else:
        order = {"downloaded": 0, "installed": 1, "updated": 1, "confirmed": 2}
        if row.skill_version_id != skill_version_id:
            row.state = "updated" if row.state in ("installed", "confirmed", "updated") else state
        elif row.state == "removed" or order.get(state, 0) > order.get(row.state, 0):
            row.state = state
        row.skill_version_id = skill_version_id
        row.channel = channel
        row.kind = kind
        row.device_id = device_id or row.device_id
    if state == "installed":
        row.installed_at = utcnow()
    await session.flush()
    await refresh_install_count(session, skill_id)
    return row


async def confirm_from_run(
    session: AsyncSession, *, user_id: str | None, device_id: str | None, skill_id: str, version_id: str | None
) -> Installation | None:
    if user_id is None:
        return None
    stmt = select(Installation).where(
        Installation.user_id == user_id, Installation.skill_id == skill_id, Installation.state != "removed"
    )
    if device_id:
        stmt = stmt.where(Installation.device_key == device_id)
    row = (await session.execute(stmt.order_by(Installation.updated_at.desc()))).scalars().first()
    if row is None:
        return None
    now = utcnow()
    if row.confirmed_at is None:
        row.confirmed_at = now
    if row.state in ("downloaded", "installed", "updated"):
        row.state = "confirmed"
    row.last_run_at = now
    row.run_count += 1
    if version_id:
        row.skill_version_id = version_id
    return row


async def mark_removed(session: AsyncSession, installation: Installation) -> None:
    installation.state = "removed"
    await refresh_install_count(session, installation.skill_id)


async def refresh_install_count(session: AsyncSession, skill_id: str) -> None:
    count = (
        await session.execute(
            select(func.count(func.distinct(Installation.user_id))).where(
                Installation.skill_id == skill_id, Installation.state != "removed", Installation.kind == "permanent"
            )
        )
    ).scalar_one()
    skill = await session.get(Skill, skill_id)
    if skill is not None:
        skill.install_count = int(count)
