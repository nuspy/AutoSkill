"""Curated lists: admin-picked groups of published skills shown on the hub."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Conflict, NotFound
from autoskill.models.hub import CuratedList, CuratedListItem
from autoskill.models.skill import Skill
from autoskill.models.user import User
from autoskill.services.hub.catalog import visible_filter


async def public_lists(session: AsyncSession) -> list[CuratedList]:
    res = await session.execute(
        select(CuratedList).where(CuratedList.is_public.is_(True)).order_by(CuratedList.ordinal, CuratedList.slug)
    )
    return list(res.scalars())


async def all_lists(session: AsyncSession) -> list[CuratedList]:
    res = await session.execute(select(CuratedList).order_by(CuratedList.ordinal, CuratedList.slug))
    return list(res.scalars())


async def by_slug(session: AsyncSession, slug: str, *, include_private: bool = False) -> CuratedList:
    row = (await session.execute(select(CuratedList).where(CuratedList.slug == slug))).scalar_one_or_none()
    if row is None or (not row.is_public and not include_private):
        raise NotFound("list_not_found")
    return row


async def skills_of(session: AsyncSession, lst: CuratedList, user: User | None) -> list[Skill]:
    """Skills of the list the viewer may see, in list order."""
    res = await session.execute(
        select(Skill)
        .join(CuratedListItem, CuratedListItem.skill_id == Skill.id)
        .where(CuratedListItem.list_id == lst.id, *visible_filter(user))
        .order_by(CuratedListItem.ordinal, Skill.title)
    )
    return list(res.scalars())


async def item_counts(session: AsyncSession) -> dict[str, int]:
    res = await session.execute(
        select(CuratedListItem.list_id, func.count(CuratedListItem.id)).group_by(CuratedListItem.list_id)
    )
    return {list_id: int(n) for list_id, n in res.all()}


async def create_list(
    session: AsyncSession,
    *,
    slug: str,
    name: dict,
    description: str | None,
    ordinal: int,
    is_public: bool,
    actor_id: str,
) -> CuratedList:
    if (await session.execute(select(CuratedList.id).where(CuratedList.slug == slug))).first():
        raise Conflict("slug_taken")
    row = CuratedList(
        slug=slug, name=name, description=description, ordinal=ordinal, is_public=is_public, created_by=actor_id
    )
    session.add(row)
    await session.flush()
    return row


async def add_item(session: AsyncSession, lst: CuratedList, skill_id: str, note: str | None = None) -> CuratedListItem:
    skill = await session.get(Skill, skill_id)
    if skill is None or skill.current_published_version_id is None:
        raise Conflict("skill_not_published", message="Only published skills can be listed.")
    existing = (
        await session.execute(
            select(CuratedListItem).where(CuratedListItem.list_id == lst.id, CuratedListItem.skill_id == skill_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.note = note
        return existing
    count = (
        await session.execute(select(func.count(CuratedListItem.id)).where(CuratedListItem.list_id == lst.id))
    ).scalar_one()
    item = CuratedListItem(list_id=lst.id, skill_id=skill_id, ordinal=int(count), note=note)
    session.add(item)
    await session.flush()
    return item


async def remove_item(session: AsyncSession, lst: CuratedList, skill_id: str) -> None:
    existing = (
        await session.execute(
            select(CuratedListItem).where(CuratedListItem.list_id == lst.id, CuratedListItem.skill_id == skill_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)
