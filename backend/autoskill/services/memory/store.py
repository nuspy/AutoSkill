"""Append-only skill memory with supersede/archive semantics."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.db.base import utcnow
from autoskill.models.memory import MEMORY_KINDS, SkillMemoryEntry


async def add_entry(
    session: AsyncSession,
    skill_id: str,
    *,
    kind: str,
    title: str,
    body: str,
    structured: dict | None = None,
    step_key: str | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    skill_version_id: str | None = None,
    author_user_id: str | None = None,
    status: str = "active",
    tags: list[str] | None = None,
) -> SkillMemoryEntry:
    if kind not in MEMORY_KINDS:
        raise ValidationFailed("unknown_memory_kind", kind=kind)
    entry = SkillMemoryEntry(
        skill_id=skill_id,
        kind=kind,
        title=title.strip()[:200],
        body=body.strip(),
        structured=structured or {},
        step_key=step_key,
        source=source,
        source_ref=source_ref,
        skill_version_id=skill_version_id,
        author_user_id=author_user_id,
        status=status,
        tags=tags or [],
    )
    session.add(entry)
    await session.flush()
    return entry


async def supersede(
    session: AsyncSession, entry_id: str, *, title: str, body: str, structured: dict | None, author_user_id: str | None
) -> SkillMemoryEntry:
    old = await session.get(SkillMemoryEntry, entry_id)
    if old is None:
        raise NotFound("memory_entry_not_found")
    new = await add_entry(
        session,
        old.skill_id,
        kind=old.kind,
        title=title,
        body=body,
        structured=structured or old.structured,
        step_key=old.step_key,
        source="manual",
        author_user_id=author_user_id,
        tags=old.tags,
    )
    old.status = "superseded"
    old.superseded_by_id = new.id
    return new


async def set_status(session: AsyncSession, entry_id: str, status: str) -> SkillMemoryEntry:
    entry = await session.get(SkillMemoryEntry, entry_id)
    if entry is None:
        raise NotFound("memory_entry_not_found")
    entry.status = status
    if status == "archived":
        entry.archived_at = utcnow()
    return entry


async def list_entries(
    session: AsyncSession,
    skill_id: str,
    *,
    status: str | None = "active",
    kind: str | None = None,
    step_key: str | None = None,
) -> list[SkillMemoryEntry]:
    stmt = select(SkillMemoryEntry).where(SkillMemoryEntry.skill_id == skill_id)
    if status:
        stmt = stmt.where(SkillMemoryEntry.status == status)
    if kind:
        stmt = stmt.where(SkillMemoryEntry.kind == kind)
    if step_key:
        stmt = stmt.where(SkillMemoryEntry.step_key == step_key)
    res = await session.execute(stmt.order_by(SkillMemoryEntry.created_at))
    return list(res.scalars().all())
