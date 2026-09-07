"""How many tokens an automatic task may write.

Every automatic task (interview, drafting, review, memory extraction...) used to carry its own
hard-coded ceiling. Those numbers were guesses made for models that answer directly: a reasoning
model spends a large part of the budget thinking before writing, so a ceiling of a few thousand
tokens ends the request with `finish_reason="length"` and an empty body — which looks like "the
model produced no output" and is in fact "we did not let it finish".

The ceiling is now a system setting, off by default: no limit means the provider decides, which
for a local model is its own context. Administration -> Settings turns it on when the spend has
to be capped.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.services.settings import get_setting


async def output_budget(session: AsyncSession) -> int | None:
    """Ceiling for one call, or None to leave it to the provider.

    One number for every automatic task: an administrator who sets a cap means it, and a per-task
    floor overriding it would make the setting say one thing and do another.
    """
    if not await get_setting(session, "llm_output_limit_enabled"):
        return None
    try:
        value = int(await get_setting(session, "llm_output_limit_tokens"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
