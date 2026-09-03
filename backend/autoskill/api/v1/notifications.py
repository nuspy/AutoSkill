from fastapi import APIRouter, Query
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.errors import NotFound
from autoskill.db.base import utcnow
from autoskill.models.notification import Notification, NotificationPreference
from autoskill.schemas.common import OkResponse
from autoskill.schemas.notification import NotificationList, NotificationOut, PreferenceUpdate
from autoskill.services.notifications import unread_count

router = APIRouter(prefix="/me/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
async def list_notifications(
    session: SessionDep,
    user: CurrentUser,
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=200),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    res = await session.execute(stmt.order_by(Notification.created_at.desc()).limit(limit))
    items = [NotificationOut.model_validate(n) for n in res.scalars().all()]
    return NotificationList(items=items, unread=await unread_count(session, user.id))


@router.post("/{notification_id}/read", response_model=OkResponse)
async def mark_read(notification_id: str, session: SessionDep, user: CurrentUser):
    row = await session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise NotFound("notification_not_found")
    if row.read_at is None:
        row.read_at = utcnow()
        await session.commit()
    return OkResponse()


@router.post("/read-all", response_model=OkResponse)
async def mark_all_read(session: SessionDep, user: CurrentUser):
    res = await session.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    now = utcnow()
    for row in res.scalars():
        row.read_at = now
    await session.commit()
    return OkResponse()


@router.put("/preferences", response_model=OkResponse)
async def set_preference(body: PreferenceUpdate, session: SessionDep, user: CurrentUser):
    res = await session.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user.id, NotificationPreference.kind == body.kind
        )
    )
    pref = res.scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user.id, kind=body.kind)
        session.add(pref)
    pref.in_app, pref.email = body.in_app, body.email
    await session.commit()
    return OkResponse()
