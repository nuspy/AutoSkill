"""Long poll for the next interview turn — the sibling of `tester/checkpoints.wait_for_decision`.

The agent cannot be pushed to: everything the application asks of it rides back on a request the
agent itself made. So the agent asks "what should I do next?" and this holds the answer open for a
short while rather than returning an empty reply immediately.

Short polls repeated, never one long request. A quarter of an hour spent inside a single HTTP call
dies to any proxy hiccup, a laptop lid or a worker restart, and leaves the caller unable to tell
whether the turn was ever produced. Fifty seconds is the shape already proven here for checkpoints,
and the interview itself may take minutes: the loop simply runs again.
"""

from __future__ import annotations

import asyncio
from typing import Any

from autoskill.models.interview import InterviewSession
from autoskill.models.procedure import Procedure

MAX_WAIT_S = 50
# a second rather than the checkpoints' half: this re-read competes with the interview job for the
# SQLite writer lock, and nothing here is worth that contention
POLL_INTERVAL_S = 1.0


async def wait_for_turn(session_factory, interview_id: str, timeout_s: int) -> dict[str, Any]:
    """Return the current turn, waiting until the procedure stops running or the time runs out.

    `timeout_s = 0` returns at once — which is what keeps the test suite instant.
    """
    from autoskill.services.interview import service

    deadline = asyncio.get_event_loop().time() + max(0, min(timeout_s, MAX_WAIT_S))
    while True:
        # read-only on purpose: the caller has already recorded the visit on the request's own
        # session and committed it. Writing from here would hold SQLite's single writer against the
        # interview job for as long as the poll lasts.
        async with session_factory() as session:
            interview = await session.get(InterviewSession, interview_id)
            if interview is None:
                from autoskill.core.errors import NotFound

                raise NotFound("interview_not_found")
            procedure = await session.get(Procedure, interview.procedure_id)
            settled = procedure is None or procedure.state != "running"
            if settled or asyncio.get_event_loop().time() >= deadline:
                return await service.turn_view(session, interview)
        await asyncio.sleep(POLL_INTERVAL_S)
