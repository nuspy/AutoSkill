from autoskill.core.jobs import JobContext, job
from autoskill.services.interview.service import run_interview


@job("interview.run")
async def interview_run(ctx: JobContext, session_id: str, **_) -> dict:
    await run_interview(session_id)
    return {"session_id": session_id}
