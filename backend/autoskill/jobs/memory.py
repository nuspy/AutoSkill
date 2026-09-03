"""Memory extraction job: turns trial discussions and improvement analyses into skill memory."""

from __future__ import annotations

from autoskill.core.events import emit, project_channel
from autoskill.core.jobs import JobContext, job
from autoskill.db.session import get_session_factory
from autoskill.services.memory.extract import extract_after_proposal, extract_after_trial


@job("memory.extract")
async def memory_extract(
    ctx: JobContext, skill_id: str, source: str, source_ref: str, language: str = "en", **_
) -> dict:
    async with get_session_factory()() as session:
        if source == "trial_discussion":
            created, error = await extract_after_trial(session, source_ref, language)
        elif source == "improvement":
            created, error = await extract_after_proposal(session, source_ref, language)
        else:
            return {"created": 0, "error": f"unknown source {source}"}
        await session.commit()
        project_id = ctx.project_id
    if project_id:
        await emit(project_channel(project_id), "memory.updated", {"skill_id": skill_id, "created": created})
    return {"created": created, "error": error}
