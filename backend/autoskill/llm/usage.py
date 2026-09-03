"""Record token usage per project/provider/day."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.db.base import utcnow
from autoskill.llm.provider import Usage
from autoskill.models.usage import ProjectUsageDaily


async def record_usage(session: AsyncSession, project_id: str | None, provider_id: str | None, usage: Usage) -> None:
    if not project_id:
        return
    day = utcnow().strftime("%Y-%m-%d")
    res = await session.execute(
        select(ProjectUsageDaily).where(
            ProjectUsageDaily.project_id == project_id,
            ProjectUsageDaily.date == day,
            ProjectUsageDaily.provider_id == provider_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = ProjectUsageDaily(
            project_id=project_id,
            date=day,
            provider_id=provider_id,
            input_tokens=0,
            output_tokens=0,
            calls=0,
            cost_estimate=0.0,
        )
        session.add(row)
    row.input_tokens += usage.input_tokens
    row.output_tokens += usage.output_tokens
    row.calls += 1


async def usage_today(session: AsyncSession, project_id: str) -> int:
    day = utcnow().strftime("%Y-%m-%d")
    res = await session.execute(
        select(ProjectUsageDaily).where(ProjectUsageDaily.project_id == project_id, ProjectUsageDaily.date == day)
    )
    return sum(r.input_tokens + r.output_tokens for r in res.scalars())
