"""Propose skill memory entries from a transcript (interview, trial discussions, improvement analysis).

One LLM call with structured output; entries are stored with the given source so the person can see
where each note came from. Extraction never blocks the caller: errors are returned, not raised.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.llm.provider import ChatMessage, ChatRequest
from autoskill.llm.registry import get_provider
from autoskill.llm.structured import structured
from autoskill.llm.usage import record_usage
from autoskill.models.improvement import ImprovementProposal
from autoskill.models.interview import KnowledgeDoc
from autoskill.models.skill import Skill
from autoskill.models.trial import StepDiscussion, TrialSession, TrialSnapshot
from autoskill.prompts import render
from autoskill.schemas.knowledge import MemoryExtraction
from autoskill.services.memory.store import add_entry

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "hu": "Hungarian", "de": "German", "es": "Spanish", "fr": "French"}


async def extract_memory(
    session: AsyncSession,
    *,
    skill_id: str,
    project_id: str,
    purpose: str,
    language: str,
    knowledge_json: str,
    transcript: list[dict],
    context_kind: str,
    source: str,
    source_ref: str | None,
    system_prompt: str | None = None,
    status: str = "active",
) -> tuple[int, str | None]:
    """Return (entries created, error). Uses the provider configured for `purpose`."""
    if not transcript:
        return 0, None
    provider, provider_id = await get_provider(session, project_id, purpose)
    messages = []
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))
    messages.append(
        ChatMessage(
            role="user",
            content=render(
                "memory_extract",
                language_name=LANGUAGE_NAMES.get(language, "English"),
                knowledge_json=knowledge_json,
                transcript=transcript,
                context_kind=context_kind,
            ),
        )
    )
    try:
        result = await structured(
            provider,
            ChatRequest(messages=messages, temperature=0.1, max_tokens=3000, seed=7, purpose=purpose),
            MemoryExtraction,
        )
    except Exception as exc:  # noqa: BLE001 - memory is best effort
        return 0, str(exc)[:500]
    await record_usage(session, project_id, provider_id, result.usage)
    created = 0
    for entry in result.value.entries:
        await add_entry(
            session,
            skill_id,
            kind=entry.kind,
            title=entry.title,
            body=entry.body,
            structured=entry.structured,
            step_key=entry.step_key,
            source=source,
            source_ref=source_ref,
            status=status,
        )
        created += 1
    return created, None


async def _knowledge_json(session: AsyncSession, skill_id: str) -> str:
    res = await session.execute(
        select(KnowledgeDoc).where(KnowledgeDoc.skill_id == skill_id).order_by(KnowledgeDoc.revision.desc()).limit(1)
    )
    doc = res.scalar_one_or_none()
    return json.dumps(doc.doc, ensure_ascii=False)[:12000] if doc else "{}"


async def extract_after_trial(session: AsyncSession, trial_id: str, language: str = "en") -> tuple[int, str | None]:
    """Corrections, coach discussions and the summary of a finished trial become memory."""
    trial = await session.get(TrialSession, trial_id)
    if trial is None:
        return 0, "trial_not_found"
    transcript: list[dict] = []
    for c in trial.corrections:
        transcript.append({"role": "user", "content": f"[correction on step {c.get('step_key')}] {c.get('text', '')}"})
    res = await session.execute(
        select(StepDiscussion).where(StepDiscussion.trial_session_id == trial.id).order_by(StepDiscussion.created_at)
    )
    for disc in res.scalars():
        for m in disc.messages:
            transcript.append(
                {"role": m.get("role", "user"), "content": f"[step {disc.step_key}] {str(m.get('content', ''))[:1500]}"}
            )
    snaps = await session.execute(
        select(TrialSnapshot).where(TrialSnapshot.trial_session_id == trial.id, TrialSnapshot.restored_at.is_not(None))
    )
    for snap in snaps.scalars():
        transcript.append(
            {
                "role": "user",
                "content": f"[restore] step {snap.step_key} restored from its backup (iteration {snap.iteration}): "
                + json.dumps(snap.restore_result or {}, ensure_ascii=False)[:800],
            }
        )
    if trial.summary:
        transcript.append({"role": "assistant", "content": f"[trial summary] {trial.summary[:3000]}"})
    return await extract_memory(
        session,
        skill_id=trial.skill_id,
        project_id=trial.project_id,
        purpose="coach",
        language=language,
        knowledge_json=await _knowledge_json(session, trial.skill_id),
        transcript=transcript,
        context_kind="trial",
        source="trial_discussion",
        source_ref=trial.id,
    )


async def extract_after_proposal(
    session: AsyncSession, proposal_id: str, language: str = "en"
) -> tuple[int, str | None]:
    """The analysis and rationale of an improvement proposal become (proposed) memory."""
    proposal = await session.get(ImprovementProposal, proposal_id)
    if proposal is None:
        return 0, "proposal_not_found"
    skill = await session.get(Skill, proposal.skill_id)
    analysis = proposal.analysis or {}
    transcript = [
        {"role": "assistant", "content": "[analysis] " + json.dumps(analysis, ensure_ascii=False)[:6000]},
    ]
    if proposal.rationale:
        transcript.append({"role": "assistant", "content": "[rationale] " + proposal.rationale[:3000]})
    return await extract_memory(
        session,
        skill_id=proposal.skill_id,
        project_id=skill.project_id if skill else proposal.project_id,
        purpose="analyst",
        language=language,
        knowledge_json=await _knowledge_json(session, proposal.skill_id),
        transcript=transcript,
        context_kind="improvement",
        source="improvement",
        source_ref=proposal.id,
        status="proposed",
    )
