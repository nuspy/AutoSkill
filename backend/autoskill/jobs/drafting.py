from autoskill.core.errors import AppError
from autoskill.core.jobs import JobContext, job
from autoskill.db.session import get_session_factory
from autoskill.services.drafting.author import generate_draft


@job("draft.generate")
async def draft_generate(
    ctx: JobContext,
    skill_id: str,
    user_id: str | None = None,
    mode: str = "new",
    instructions: str | None = None,
    base_version_id: str | None = None,
    origin: str = "interview",
    language: str = "en",
    interview_id: str | None = None,
    **_,
) -> dict:
    try:
        async with get_session_factory()() as session:
            try:
                version = await generate_draft(
                    session,
                    skill_id=skill_id,
                    user_id=user_id,
                    mode=mode,
                    instructions=instructions,
                    base_version_id=base_version_id,
                    origin=origin,
                    language=language,
                    progress=ctx.progress,
                )
            except AppError as exc:
                raise RuntimeError(f"{exc.code}: {exc.message}") from exc
            return {"version_id": version.id, "version": version.version}
    finally:
        if interview_id:
            await _release_interview(interview_id)


async def _release_interview(interview_id: str) -> None:
    """Take the interview out of `drafting_requested`, whatever became of the draft.

    The interview itself was over the moment the summary was confirmed — `finalize` marks it
    `complete` and commits — and `drafting_requested` only ever meant "and a first draft is now being
    written". Nothing used to clear it, so a session that had succeeded in every single way came to
    rest in a state the interview page reads as *still working*: a spinner over a finished interview,
    for ever, while the draft sat ready in the versions tab.

    It runs in `finally` because a draft that fails strands the interview exactly as thoroughly as
    one that succeeds — and a failed draft is reported on its own `jobs` row, which is where it
    belongs. Failing to release must not itself fail the job, whose real work is already done.
    """
    from autoskill.models.interview import InterviewSession
    from autoskill.services.procedures.defs.interview import _notify

    try:
        async with get_session_factory()() as session:
            interview = await session.get(InterviewSession, interview_id)
            if interview is None or interview.state != "drafting_requested":
                return
            interview.state = "complete"
            await session.commit()
            await _notify(interview, "interview.updated")
    except Exception:  # noqa: BLE001 - the draft is what the caller asked for; this is tidying up
        import logging

        logging.getLogger(__name__).exception("could not release interview %s from drafting", interview_id)
