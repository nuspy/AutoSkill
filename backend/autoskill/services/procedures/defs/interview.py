"""The interview procedure: deterministic flow, LLM only for content and supervision.

intake -> compute_gates -> supervise -> ask -> (wait) -> ingest -> compute_gates ...
                              \-> confirm_summary -> (wait) -> finalize
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from autoskill.core.events import emit, project_channel, user_channel
from autoskill.db.base import utcnow
from autoskill.llm.budget import output_budget
from autoskill.llm.provider import ChatMessage, ChatRequest
from autoskill.llm.registry import get_provider
from autoskill.llm.structured import structured
from autoskill.llm.usage import record_usage
from autoskill.models.data_source import DataSource
from autoskill.models.interview import InterviewMessage, InterviewSession, KnowledgeDoc
from autoskill.models.skill import Skill
from autoskill.prompts import render
from autoskill.schemas.knowledge import (
    KnowledgeDocModel,
    QuestionSpec,
    SupervisorDecision,
)
from autoskill.services.interview.gates import all_passed, completeness, compute_gates, first_failing
from autoskill.services.library.catalog import library_catalog
from autoskill.services.memory.extract import extract_memory
from autoskill.services.procedures.engine import (
    Done,
    Next,
    ProcedureContext,
    ProcedureDef,
    StepDef,
    Wait,
    register,
)

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "hu": "Hungarian", "de": "German", "es": "Spanish", "fr": "French"}
MAX_TURNS_DEFAULT = 40
# How many turns may be spent on one gate before code stops aiming at it. Three is enough for a
# person to answer, rephrase and answer again; beyond that the obstacle is not the person.
MAX_GATE_ATTEMPTS = 3


async def _session(ctx: ProcedureContext) -> InterviewSession:
    row = await ctx.session.get(InterviewSession, ctx.procedure.subject_id)
    assert row is not None
    return row


async def _knowledge(ctx: ProcedureContext, interview: InterviewSession) -> KnowledgeDoc | None:
    if interview.knowledge_id is None:
        return None
    return await ctx.session.get(KnowledgeDoc, interview.knowledge_id)


async def _save_knowledge(ctx: ProcedureContext, interview: InterviewSession, doc: KnowledgeDocModel) -> KnowledgeDoc:
    res = await ctx.session.execute(
        select(func.coalesce(func.max(KnowledgeDoc.revision), 0)).where(KnowledgeDoc.skill_id == interview.skill_id)
    )
    revision = int(res.scalar_one()) + 1
    gates = compute_gates(doc)
    row = KnowledgeDoc(
        project_id=interview.project_id,
        skill_id=interview.skill_id,
        revision=revision,
        doc=doc.model_dump(),
        completeness=completeness(gates),
        derived_from_session_id=interview.id,
        created_at=utcnow(),
    )
    ctx.session.add(row)
    await ctx.session.flush()
    interview.knowledge_id = row.id
    return row


async def _add_message(
    ctx: ProcedureContext,
    interview: InterviewSession,
    role: str,
    content: str,
    meta: dict | None = None,
    attachments: list | None = None,
) -> InterviewMessage:
    res = await ctx.session.execute(
        select(func.coalesce(func.max(InterviewMessage.ordinal), 0)).where(InterviewMessage.session_id == interview.id)
    )
    msg = InterviewMessage(
        session_id=interview.id,
        ordinal=int(res.scalar_one()) + 1,
        role=role,
        content=content,
        meta=meta or {},
        attachments=attachments or [],
        created_at=utcnow(),
    )
    ctx.session.add(msg)
    await ctx.session.flush()
    return msg


async def _notify(interview: InterviewSession, event: str, data: dict | None = None) -> None:
    payload = {"session_id": interview.id, "skill_id": interview.skill_id, "state": interview.state, **(data or {})}
    await emit(project_channel(interview.project_id), event, payload)
    await emit(user_channel(interview.user_id), event, payload)


def _lang(interview: InterviewSession) -> str:
    return LANGUAGE_NAMES.get(interview.language, "English")


async def _llm(
    ctx: ProcedureContext, interview: InterviewSession, purpose: str, prompt: str, model, temperature: float = 0.1
):
    provider, provider_id = await get_provider(purpose)
    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=render("interview_system", language_name=_lang(interview))),
            ChatMessage(role="user", content=prompt),
        ],
        temperature=temperature,
        max_tokens=await output_budget(ctx.session),
        seed=7,
        purpose=purpose,
    )
    result = await structured(provider, req, model)
    await record_usage(ctx.session, interview.project_id, provider_id, result.usage)
    usage = interview.token_usage or {}
    usage["input_tokens"] = usage.get("input_tokens", 0) + result.usage.input_tokens
    usage["output_tokens"] = usage.get("output_tokens", 0) + result.usage.output_tokens
    interview.token_usage = dict(usage)
    return result


# --- steps ------------------------------------------------------------------------------


async def intake(ctx: ProcedureContext):
    interview = await _session(ctx)
    interview.state = "intake"
    res = await ctx.session.execute(select(DataSource).where(DataSource.project_id == interview.project_id))
    # access notes and schema come along: gate G2 demands them, so withholding them from the model
    # made the interview ask for what the project had already recorded
    sources = [
        {
            "name": d.name,
            "kind": d.kind,
            "description": d.description,
            "access": d.access_notes,
            "sensitivity": d.sensitivity,
            "fields": list((d.schema_def or {}).get("fields") or []),
        }
        for d in res.scalars()
    ]
    prompt = render(
        "interview_intake",
        description=ctx.state.get("description", ""),
        attachments=ctx.state.get("attachments", []),
        data_sources=sources,
        language_name=_lang(interview),
        library=await library_catalog(ctx.session),
    )
    result = await _llm(ctx, interview, "interviewer", prompt, KnowledgeDocModel)
    doc: KnowledgeDocModel = result.value
    doc.human_confirmed = False
    await _save_knowledge(ctx, interview, doc)
    interview.state = "exploring"
    return Next(usage=result.usage.as_dict())


async def compute_gates_step(ctx: ProcedureContext):
    interview = await _session(ctx)
    knowledge = await _knowledge(ctx, interview)
    assert knowledge is not None
    doc = KnowledgeDocModel.model_validate(knowledge.doc)
    gates = compute_gates(doc)
    knowledge.completeness = completeness(gates)
    ctx.state["gates"] = [g.model_dump() for g in gates]
    interview.state = "gating"
    await _notify(interview, "interview.updated", {"gates": knowledge.completeness})
    # everything but the human confirmation passes -> go straight to the summary
    if all_passed(gates, skip=("G8",)):
        return Next("confirm_summary", output={"all_gates_passed": True})
    return Next("supervise")


async def supervise(ctx: ProcedureContext):
    """LLM supervisor decides proceed / need_more / block; code enforces the gates."""
    interview = await _session(ctx)
    knowledge = await _knowledge(ctx, interview)
    assert knowledge is not None
    gates = ctx.state.get("gates", [])
    max_turns = int(ctx.state.get("max_turns", MAX_TURNS_DEFAULT))
    prompt = render(
        "interview_supervisor",
        gates=gates,
        knowledge_json=json.dumps(knowledge.doc, ensure_ascii=False),
        turn_count=interview.turn_count,
        max_turns=max_turns,
        library=await library_catalog(ctx.session),
    )
    result = await _llm(ctx, interview, "supervisor", prompt, SupervisorDecision, temperature=0.0)
    decision: SupervisorDecision = result.value
    doc = KnowledgeDocModel.model_validate(knowledge.doc)
    # A gate that has been aimed at repeatedly and still will not close is not going to close by
    # asking a seventh time: the model is failing to record the shape the gate checks for, and no
    # answer the person gives can change that. Seen for real — six consecutive turns rephrasing the
    # same question about a backup copy, each answered, each ingested, the gate red every time.
    # Setting it aside lets the interview finish and say what stayed unsettled, which is worth far
    # more than a loop that burns the turn budget and ends in "blocked".
    attempts: dict[str, int] = dict(ctx.state.get("gate_attempts") or {})
    stuck = tuple(gate_id for gate_id, tries in attempts.items() if tries >= MAX_GATE_ATTEMPTS)
    failing = first_failing(compute_gates(doc), skip=("G8", *stuck))
    # code has the final say: deterministic gates override an over-eager "proceed"
    effective = decision.decision
    if failing is not None and effective == "proceed":
        effective = "need_more"
    if failing is None and effective == "need_more":
        effective = "proceed"
    if interview.turn_count >= max_turns and effective == "need_more":
        effective = "block"
        decision.reasons.append("turn budget exhausted")
    record = {
        **decision.model_dump(),
        "effective": effective,
        "failing_gate": failing.id if failing else None,
        "exhausted_gates": list(stuck),
    }
    ctx.state["supervisor"] = record
    if effective == "proceed":
        return Next("confirm_summary", decision=record, usage=result.usage.as_dict())
    if effective == "block":
        interview.state = "failed"
        interview.error = "; ".join(decision.reasons) or "blocked by supervisor"
        await _notify(interview, "interview.updated")
        return Done({"blocked": True, "reasons": decision.reasons})
    target = decision.target_gate or (failing.id if failing else "G1")
    if target in stuck and failing is not None:
        target = failing.id  # the supervisor may still name a gate code has given up on
    attempts[target] = attempts.get(target, 0) + 1
    ctx.state["gate_attempts"] = attempts
    ctx.state["target_gate"] = target
    ctx.state["guidance"] = "; ".join(decision.missing or decision.reasons) or (failing.detail if failing else "")
    ctx.state["suggested"] = decision.next_question
    return Next("ask", decision=record, usage=result.usage.as_dict())


MAX_CONSECUTIVE_AGENT_TURNS = 3


def _executor(interview: InterviewSession) -> dict[str, Any] | None:
    """The agent attached to this session, or None. Only then may a turn be addressed to it."""
    from autoskill.services.interview.service import has_live_agent

    if not has_live_agent(interview):
        return None
    return {"agent": interview.agent_target or "the person's agent"}


def _settle_audience(ctx: ProcedureContext, q: QuestionSpec, executor: dict[str, Any] | None) -> None:
    """Code decides who answers, as it already does with the supervisor's verdict.

    Without an attached agent every turn goes to the person, which is what makes a session with no
    executor behave exactly as it did before. And the machine does not get to talk to itself for
    long while somebody waits.
    """
    if q.audience != "agent":
        q.task = None
        return
    if executor is None or q.task is None:
        q.audience, q.task = "person", None
        return
    if ctx.state.get("agent_turns", 0) >= MAX_CONSECUTIVE_AGENT_TURNS:
        q.audience, q.task = "person", None


async def ask(ctx: ProcedureContext):
    interview = await _session(ctx)
    knowledge = await _knowledge(ctx, interview)
    assert knowledge is not None
    if ctx.human_input is None:
        if interview.pending_question is None:
            executor = _executor(interview)
            prompt = render(
                "interview_question",
                language_name=_lang(interview),
                target_gate=ctx.state.get("target_gate", "G1"),
                guidance=ctx.state.get("guidance", ""),
                suggested=ctx.state.get("suggested"),
                knowledge_json=json.dumps(knowledge.doc, ensure_ascii=False),
                library=await library_catalog(ctx.session),
                executor=executor,
            )
            result = await _llm(ctx, interview, "interviewer", prompt, QuestionSpec, temperature=0.3)
            q: QuestionSpec = result.value
            q.target_gate = ctx.state.get("target_gate", q.target_gate)
            _settle_audience(ctx, q, executor)
            interview.pending_question = q.model_dump()
            await _add_message(ctx, interview, "assistant", q.question, meta={"question": q.model_dump()})
        interview.state = "awaiting_answer"
        await _notify(interview, "interview.question", {"question": interview.pending_question})
        return Wait("answer", output={"question": interview.pending_question})
    # resumed with the answer
    answer = ctx.human_input
    ctx.state["last_answer"] = answer
    asked_agent = (interview.pending_question or {}).get("audience") == "agent"
    ctx.state["answered_by"] = "agent" if asked_agent else "person"
    ctx.state["agent_turns"] = ctx.state.get("agent_turns", 0) + 1 if asked_agent else 0
    if not asked_agent:
        # only a person's answer costs a turn of the budget: looking at the machine is not a question
        interview.turn_count += 1
    await _add_message(ctx, interview, "user", answer.get("text", ""), attachments=answer.get("attachments", []))
    return Next("ingest")


async def ingest(ctx: ProcedureContext):
    interview = await _session(ctx)
    knowledge = await _knowledge(ctx, interview)
    assert knowledge is not None
    question = interview.pending_question or {}
    answer = ctx.state.get("last_answer", {})
    prompt = render(
        "interview_ingest",
        question=question.get("question", ""),
        target_gate=question.get("target_gate", ""),
        answer=answer.get("text", ""),
        attachments=answer.get("attachments", []),
        knowledge_json=json.dumps(knowledge.doc, ensure_ascii=False),
        answered_by=ctx.state.get("answered_by", "person"),
    )
    result = await _llm(ctx, interview, "interviewer", prompt, KnowledgeDocModel)
    doc: KnowledgeDocModel = result.value
    doc.human_confirmed = False
    await _save_knowledge(ctx, interview, doc)
    interview.pending_question = None
    interview.state = "exploring"
    return Next("compute_gates", usage=result.usage.as_dict())


async def confirm_summary(ctx: ProcedureContext):
    interview = await _session(ctx)
    knowledge = await _knowledge(ctx, interview)
    assert knowledge is not None
    if ctx.human_input is None:
        if not ctx.state.get("summary_text"):
            provider, provider_id = await get_provider("interviewer")
            req = ChatRequest(
                messages=[
                    ChatMessage(role="system", content=render("interview_system", language_name=_lang(interview))),
                    ChatMessage(
                        role="user",
                        content=render(
                            "interview_summary",
                            language_name=_lang(interview),
                            knowledge_json=json.dumps(knowledge.doc, ensure_ascii=False),
                        ),
                    ),
                ],
                temperature=0.2,
                max_tokens=await output_budget(ctx.session),
                purpose="interviewer",
            )
            res = await provider.chat(req)
            await record_usage(ctx.session, interview.project_id, provider_id, res.usage)
            ctx.state["summary_text"] = res.text
            await _add_message(ctx, interview, "assistant", res.text, meta={"summary": True})
        interview.state = "awaiting_confirmation"
        interview.pending_question = {
            "question": ctx.state["summary_text"],
            "expects": "confirmation",
            "target_gate": "G8",
            "why": "",
            "options": [],
        }
        await _notify(interview, "interview.summary", {"summary": ctx.state["summary_text"]})
        return Wait("confirmation", output={"summary": ctx.state["summary_text"]})
    decision = ctx.human_input
    doc = KnowledgeDocModel.model_validate(knowledge.doc)
    await _add_message(
        ctx,
        interview,
        "user",
        decision.get("text") or ("OK" if decision.get("confirmed") else "No"),
        meta={"confirmation": decision},
    )
    ctx.state["summary_text"] = None
    interview.pending_question = None
    interview.turn_count += 1
    if decision.get("confirmed"):
        doc.human_confirmed = True
        await _save_knowledge(ctx, interview, doc)
        return Next("finalize")
    # rejected: the correction becomes an open question handled by the normal loop
    correction = decision.get("text") or "The person did not confirm the summary."
    doc.human_confirmed = False
    doc.open_questions.append(f"Correction from the person: {correction}")
    await _save_knowledge(ctx, interview, doc)
    ctx.state["last_answer"] = {"text": correction, "attachments": []}
    interview.pending_question = {
        "question": "Summary correction",
        "target_gate": "G7",
        "expects": "text",
        "why": "",
        "options": [],
    }
    return Next("ingest")


async def finalize(ctx: ProcedureContext):
    interview = await _session(ctx)
    knowledge = await _knowledge(ctx, interview)
    assert knowledge is not None
    knowledge.frozen = True
    doc = KnowledgeDocModel.model_validate(knowledge.doc)
    skill = await ctx.session.get(Skill, interview.skill_id)
    if skill is not None:
        if doc.task.name and (skill.title == skill.name or not skill.summary):
            skill.title = doc.task.name[:200]
        skill.summary = doc.task.goal[:2000] or skill.summary
    # memory extraction (LLM content, human may edit later)
    res = await ctx.session.execute(
        select(InterviewMessage).where(InterviewMessage.session_id == interview.id).order_by(InterviewMessage.ordinal)
    )
    transcript = [{"role": m.role, "content": m.content[:1500]} for m in res.scalars()]
    extracted, mem_error = await extract_memory(
        ctx.session,
        skill_id=interview.skill_id,
        project_id=interview.project_id,
        purpose="interviewer",
        language=interview.language,
        knowledge_json=json.dumps(knowledge.doc, ensure_ascii=False),
        transcript=transcript,
        context_kind="interview",
        source="interview",
        source_ref=interview.id,
        system_prompt=render("interview_system", language_name=_lang(interview)),
    )
    if mem_error:
        ctx.state["memory_error"] = mem_error
    interview.state = "complete"
    interview.completed_at = utcnow()
    await ctx.session.commit()
    await _notify(interview, "interview.updated", {"memory_entries": extracted})
    if ctx.state.get("auto_draft", True):
        from autoskill.core.jobs import get_job_runner

        await get_job_runner().enqueue(
            "draft.generate",
            {
                "skill_id": interview.skill_id,
                "user_id": interview.user_id,
                "mode": "new",
                "origin": "interview",
                "language": interview.language,
                # so the job can put the interview back when it is done: `drafting_requested` reads
                # as "still working" everywhere, and only the job knows when that stops being true
                "interview_id": interview.id,
            },
            project_id=interview.project_id,
            user_id=interview.user_id,
        )
        interview.state = "drafting_requested"
    return Done({"knowledge_id": knowledge.id, "memory_entries": extracted})


async def snapshot_interview(session, procedure) -> dict[str, Any]:
    """What a step of this procedure can change, beyond `procedure.context`.

    Knowledge docs and messages are append-only, so the snapshot only records *how far* they had
    got: the revision in use and the last visible message. Restoring rewinds those pointers, it
    never deletes what was written.
    """
    interview = await session.get(InterviewSession, procedure.subject_id)
    if interview is None:
        return {}
    res = await session.execute(
        select(func.coalesce(func.max(InterviewMessage.ordinal), 0)).where(
            InterviewMessage.session_id == interview.id
        )
    )
    return {
        "state": interview.state,
        "turn_count": interview.turn_count,
        "pending_question": interview.pending_question,
        "knowledge_id": interview.knowledge_id,
        "token_usage": dict(interview.token_usage or {}),
        "error": interview.error,
        "message_ordinal": int(res.scalar_one()),
    }


async def restore_interview(session, procedure, snap: dict[str, Any]) -> None:
    """Rewind the session to `snap`. Messages past the mark are hidden, not removed."""
    interview = await session.get(InterviewSession, procedure.subject_id)
    if interview is None or not snap:
        return
    interview.state = snap.get("state", interview.state)
    interview.turn_count = int(snap.get("turn_count") or 0)
    interview.pending_question = snap.get("pending_question")
    interview.knowledge_id = snap.get("knowledge_id")
    interview.token_usage = dict(snap.get("token_usage") or {})
    interview.error = snap.get("error")
    mark = int(snap.get("message_ordinal") or 0)
    res = await session.execute(
        select(InterviewMessage).where(InterviewMessage.session_id == interview.id)
    )
    for msg in res.scalars().all():
        meta = dict(msg.meta or {})
        # a message written after the mark belongs to a future that no longer applies; one written
        # before it may have been hidden by an earlier rewind and is now visible again
        hidden = msg.ordinal > mark
        if hidden == bool(meta.get("rewound")):
            continue
        if hidden:
            meta["rewound"] = True
        else:
            meta.pop("rewound", None)
        msg.meta = meta


register(
    ProcedureDef(
        kind="interview",
        max_iterations=400,
        snapshot=snapshot_interview,
        restore=restore_interview,
        steps=[
            StepDef("intake", "llm", intake),
            StepDef("compute_gates", "code", compute_gates_step),
            StepDef("supervise", "supervisor", supervise),
            StepDef("ask", "llm", ask),
            StepDef("ingest", "llm", ingest),
            StepDef("confirm_summary", "human_auth", confirm_summary),
            StepDef("finalize", "llm", finalize),
        ],
    )
)


def human_input_for_answer(text: str, attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"text": text, "attachments": attachments or []}
