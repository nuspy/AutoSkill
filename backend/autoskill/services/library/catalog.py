"""Catalog of enabled library components, as passed to the interviewer, supervisor and author."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.skill_version import LibraryComponent, SkillDependency


def catalog_entry(c: LibraryComponent) -> dict:
    return {
        "slug": c.slug,
        "kind": c.kind,
        "name": c.name,
        "version": c.version,
        "description": c.description,
        "tools": c.tools,
        "env_requirements": c.env_requirements,
        "install": c.install,
        "tags": c.tags,
    }


async def library_catalog(session: AsyncSession) -> list[dict]:
    res = await session.execute(
        select(LibraryComponent).where(LibraryComponent.is_enabled.is_(True)).order_by(LibraryComponent.slug)
    )
    return [catalog_entry(c) for c in res.scalars()]


async def components_for_version(
    session: AsyncSession, version_id: str
) -> list[tuple[SkillDependency, LibraryComponent]]:
    """Dependencies declared by a version, joined with the (possibly disabled) component rows."""
    deps = (
        (await session.execute(select(SkillDependency).where(SkillDependency.skill_version_id == version_id)))
        .scalars()
        .all()
    )
    out: list[tuple[SkillDependency, LibraryComponent]] = []
    for dep in deps:
        comp = (
            await session.execute(select(LibraryComponent).where(LibraryComponent.slug == dep.component_slug))
        ).scalar_one_or_none()
        if comp is not None:
            out.append((dep, comp))
    return out
