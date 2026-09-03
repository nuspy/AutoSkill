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
    **_,
) -> dict:
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
