from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.skill_version import SkillVersion

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse(version: str) -> tuple[int, int, int]:
    m = SEMVER_RE.match(version)
    if not m:
        raise ValueError(f"invalid semver {version!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump(version: str, part: str) -> str:
    major, minor, patch = parse(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


async def latest_version(session: AsyncSession, skill_id: str) -> SkillVersion | None:
    res = await session.execute(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id, SkillVersion.state != "discarded")
        .order_by(SkillVersion.major.desc(), SkillVersion.minor.desc(), SkillVersion.patch.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def next_version(session: AsyncSession, skill_id: str, part: str = "patch") -> str:
    latest = await latest_version(session, skill_id)
    if latest is None:
        return "0.1.0"
    return bump(latest.version, part)
