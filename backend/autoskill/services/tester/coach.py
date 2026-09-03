"""Step discussions with the coach: structured outcome, instruction patch, memory proposals."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import NotFound
from autoskill.db.base import utcnow
from autoskill.llm.provider import ChatMessage, ChatRequest
from autoskill.llm.registry import get_provider
from autoskill.llm.structured import structured
from autoskill.llm.usage import record_usage
from autoskill.models.skill import Skill
from autoskill.models.skill_version import StepDefinition
from autoskill.models.trial import Checkpoint, StepDiscussion, TrialSession
from autoskill.prompts import render
from autoskill.services.memory.context import memory_context
from autoskill.services.memory.store import add_entry

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "hu": "Hungarian", "de": "German", "es": "Spanish", "fr": "French"}


class CoachMemoryEntry(BaseModel):
    kind: Literal["human_procedure", "technical_note", "integration_note", "decision", "lesson_learned", "data_note"]
    title: str
    body: str


class CoachOutcome(BaseModel):
    reply: str
    no_change: bool = True
    new_instruction: str | None = None
    change_summary: str | None = None
    memory_entries: list[CoachMemoryEntry] = Field(default_factory=list)


async def open_discussion(
    session: AsyncSession,
    *,
    skill: Skill,
    version_id: str,
    step_key: str,
    user_id: str,
    trial: TrialSession | None,
    checkpoint: Checkpoint | None,
) -> StepDiscussion:
    if checkpoint is not None:
        res = await session.execute(
            select(StepDiscussion).where(StepDiscussion.checkpoint_id == checkpoint.id, StepDiscussion.state == "open")
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing
    disc = StepDiscussion(
        skill_id=skill.id,
        skill_version_id=version_id,
        trial_session_id=trial.id if trial else None,
        checkpoint_id=checkpoint.id if checkpoint else None,
        step_key=step_key,
        user_id=user_id,
    )
    session.add(disc)
    await session.flush()
    return disc


async def coach_turn(
    session: AsyncSession, disc: StepDiscussion, user_message: str, language: str = "en"
) -> CoachOutcome:
    skill = await session.get(Skill, disc.skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    res = await session.execute(
        select(StepDefinition).where(
            StepDefinition.skill_version_id == disc.skill_version_id, StepDefinition.key == disc.step_key
        )
    )
    step = res.scalar_one_or_none()
    if step is None:
        raise NotFound("step_not_found")
    checkpoint = await session.get(Checkpoint, disc.checkpoint_id) if disc.checkpoint_id else None
    trial = await session.get(TrialSession, disc.trial_session_id) if disc.trial_session_id else None
    messages = [*disc.messages, {"role": "user", "content": user_message, "at": utcnow().isoformat()}]
    provider, provider_id = await get_provider(session, skill.project_id, "coach")
    lang = LANGUAGE_NAMES.get(language, "English")
    prompt = render(
        "coach_turn",
        step=step,
        checkpoint=checkpoint,
        checkpoint_json=json.dumps(checkpoint.proposal, ensure_ascii=False) if checkpoint else "",
        corrections=trial.corrections if trial else [],
        memory=await memory_context(session, skill.id, budget_tokens=1500, step_key=step.key),
        messages=messages,
        language_name=lang,
    )
    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=render("coach_system", language_name=lang)),
            ChatMessage(role="user", content=prompt),
        ],
        temperature=0.2,
        max_tokens=2000,
        purpose="coach",
    )
    result = await structured(provider, req, CoachOutcome)
    await record_usage(session, skill.project_id, provider_id, result.usage)
    outcome: CoachOutcome = result.value
    if outcome.new_instruction:
        outcome.no_change = False
    messages.append(
        {
            "role": "assistant",
            "content": outcome.reply,
            "at": utcnow().isoformat(),
            "proposal": outcome.model_dump(exclude={"reply"}) if not outcome.no_change else None,
        }
    )
    disc.messages = messages
    return outcome


async def apply_outcome(session: AsyncSession, disc: StepDiscussion, outcome: CoachOutcome, user_id: str) -> dict:
    """Apply an accepted proposal: patch the step instruction (and package), store memory. Returns what changed."""
    from autoskill.services.trials.sync import patch_step_instruction

    changed: dict = {"instruction_updated": False, "memory_entries": 0}
    if outcome.new_instruction:
        await patch_step_instruction(
            session, disc.skill_version_id, disc.step_key, outcome.new_instruction, note=outcome.change_summary
        )
        changed["instruction_updated"] = True
    for entry in outcome.memory_entries:
        await add_entry(
            session,
            disc.skill_id,
            kind=entry.kind,
            title=entry.title,
            body=entry.body,
            step_key=disc.step_key,
            source="trial_discussion",
            source_ref=disc.id,
            skill_version_id=disc.skill_version_id,
            author_user_id=user_id,
        )
        changed["memory_entries"] += 1
    disc.state = "closed"
    disc.outcome = {**changed, "change_summary": outcome.change_summary}
    return changed
