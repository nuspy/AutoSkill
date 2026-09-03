from autoskill.core.errors import AppError
from autoskill.core.jobs import JobContext, job
from autoskill.db.session import get_session_factory
from autoskill.services.mcpgen.generator import generate_mcp


@job("mcp.generate")
async def mcp_generate(ctx: JobContext, version_id: str, user_id: str | None = None, **_) -> dict:
    async with get_session_factory()() as session:
        try:
            mv = await generate_mcp(session, version_id=version_id, user_id=user_id, progress=ctx.progress)
        except AppError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc
        return {"mcp_version_id": mv.id, "tools": len(mv.tools)}
