"""Star ratings on hub skills (one per user and skill), with cached average on the skill."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.hub import Rating
from autoskill.models.skill import Skill


async def rate(
    session: AsyncSession, *, skill: Skill, user_id: str, stars: int, comment: str | None, version_id: str | None
) -> Rating:
    row = (
        await session.execute(select(Rating).where(Rating.skill_id == skill.id, Rating.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = Rating(skill_id=skill.id, user_id=user_id, stars=stars)
        session.add(row)
    row.stars = stars
    row.comment = (comment or "").strip()[:2000] or None
    row.skill_version_id = version_id
    await session.flush()
    await refresh_stats(session, skill)
    return row


async def unrate(session: AsyncSession, *, skill: Skill, user_id: str) -> bool:
    row = (
        await session.execute(select(Rating).where(Rating.skill_id == skill.id, Rating.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    await refresh_stats(session, skill)
    return True


async def refresh_stats(session: AsyncSession, skill: Skill) -> None:
    avg, count = (
        await session.execute(select(func.avg(Rating.stars), func.count(Rating.id)).where(Rating.skill_id == skill.id))
    ).one()
    skill.rating_count = int(count or 0)
    skill.rating_avg = round(float(avg), 2) if avg is not None else None


async def list_ratings(session: AsyncSession, skill_id: str, limit: int = 50) -> list[Rating]:
    res = await session.execute(
        select(Rating).where(Rating.skill_id == skill_id).order_by(Rating.updated_at.desc()).limit(limit)
    )
    return list(res.scalars())
