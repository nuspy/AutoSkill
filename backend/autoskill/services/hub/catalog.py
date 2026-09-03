"""Hub catalog queries: what is visible, featured, latest, most installed, search."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.hub import Category, Favorite
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.models.user import User


def visible_filter(user: User | None):
    """Published skills that are shared (any logged-in user) or public (also anonymous)."""
    base = [Skill.archived_at.is_(None), Skill.current_published_version_id.is_not(None)]
    if user is None:
        return [*base, Skill.visibility == "public"]
    return [*base, Skill.visibility.in_(("shared", "public"))]


async def featured(session: AsyncSession, user: User | None, limit: int = 6) -> list[Skill]:
    res = await session.execute(
        select(Skill)
        .where(*visible_filter(user), Skill.is_featured.is_(True))
        .order_by(Skill.featured_at.desc())
        .limit(limit)
    )
    return list(res.scalars())


async def latest(session: AsyncSession, user: User | None, limit: int = 8) -> list[Skill]:
    res = await session.execute(
        select(Skill).where(*visible_filter(user)).order_by(Skill.published_at.desc()).limit(limit)
    )
    return list(res.scalars())


async def most_installed(session: AsyncSession, user: User | None, limit: int = 8) -> list[Skill]:
    res = await session.execute(
        select(Skill)
        .where(*visible_filter(user))
        .order_by(Skill.install_count.desc(), Skill.published_at.desc())
        .limit(limit)
    )
    return list(res.scalars())


async def top_rated(session: AsyncSession, user: User | None, limit: int = 8) -> list[Skill]:
    res = await session.execute(
        select(Skill)
        .where(*visible_filter(user), Skill.rating_count > 0)
        .order_by(Skill.rating_avg.desc(), Skill.rating_count.desc())
        .limit(limit)
    )
    return list(res.scalars())


async def search(
    session: AsyncSession,
    user: User | None,
    *,
    q: str | None,
    category_id: str | None,
    tag: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[Skill], int]:
    stmt = select(Skill).where(*visible_filter(user))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Skill.title).like(like),
                func.lower(Skill.name).like(like),
                func.lower(func.coalesce(Skill.summary, "")).like(like),
            )
        )
    if category_id:
        stmt = stmt.where(Skill.category_id == category_id)
    if tag:
        stmt = stmt.where(func.lower(func.cast(Skill.tags, __import__("sqlalchemy").String)).like(f'%"{tag.lower()}"%'))
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    order = {
        "installs": Skill.install_count.desc(),
        "rating": Skill.rating_avg.desc().nullslast(),
        "updated": Skill.updated_at.desc(),
        "title": Skill.title.asc(),
    }.get(sort, Skill.published_at.desc())
    res = await session.execute(stmt.order_by(order).limit(limit).offset(offset))
    return list(res.scalars()), total


async def categories(session: AsyncSession) -> list[Category]:
    res = await session.execute(select(Category).order_by(Category.ordinal, Category.slug))
    return list(res.scalars())


async def category_counts(session: AsyncSession, user: User | None) -> dict[str, int]:
    res = await session.execute(
        select(Skill.category_id, func.count(Skill.id)).where(*visible_filter(user)).group_by(Skill.category_id)
    )
    return {row[0]: int(row[1]) for row in res.all() if row[0]}


async def favorite_ids(session: AsyncSession, user: User | None) -> set[str]:
    if user is None:
        return set()
    res = await session.execute(select(Favorite.skill_id).where(Favorite.user_id == user.id))
    return {r[0] for r in res.all()}


async def published_version(session: AsyncSession, skill: Skill) -> SkillVersion | None:
    if not skill.current_published_version_id:
        return None
    return await session.get(SkillVersion, skill.current_published_version_id)
