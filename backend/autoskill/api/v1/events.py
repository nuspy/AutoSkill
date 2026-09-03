"""Server-Sent Events streams (per user and per project)."""

import asyncio

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.events import get_event_bus, project_channel, user_channel
from autoskill.core.permissions import require_project_role
from autoskill.models.project import ProjectRole

router = APIRouter(tags=["events"])


async def _stream(request: Request, channel: str):
    bus = get_event_bus()
    subscription = bus.subscribe(channel)
    await subscription.open()
    yield {"event": "ready", "data": "{}"}
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(subscription.__anext__(), timeout=25)
            except TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue
            yield {"event": event.type, "data": event.to_json()}
    finally:
        await subscription.aclose()


@router.get("/me/events")
async def user_events(request: Request, user: CurrentUser):
    return EventSourceResponse(_stream(request, user_channel(user.id)))


@router.get("/projects/{project_id}/events")
async def project_events(project_id: str, request: Request, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    return EventSourceResponse(_stream(request, project_channel(project_id)))
