"""Create notifications and push them to the user's SSE channel."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.config import get_settings
from autoskill.core.events import emit, user_channel
from autoskill.models.notification import Notification, NotificationPreference
from autoskill.models.user import User
from autoskill.services.email import send_templated

NOTIFICATION_KINDS = (
    "skill_update_available",
    "review_requested",
    "review_decided",
    "authorization_requested",
    "proposal_ready",
    "issue_reported",
    "checkpoint_waiting",
    "trial_suspended_reminder",
    "contribution_received",
    "contribution_decided",
)
EMAIL_BY_DEFAULT = {
    "skill_update_available",
    "review_requested",
    "review_decided",
    "authorization_requested",
    "proposal_ready",
    "contribution_received",
    "contribution_decided",
}
SUBJECT_PATHS = {
    "skill": "/hub/s/{id}",
    "review_request": "/review/{id}",
    "improvement_proposal": "/me/notifications",
    "skill_version": "/me/notifications",
    "trial_session": "/me/trials",
}


async def notify(
    session: AsyncSession,
    user_id: str,
    kind: str,
    title: str,
    *,
    body: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    payload: dict | None = None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload or {},
    )
    session.add(row)
    await session.flush()
    unread = await unread_count(session, user_id)
    await emit(
        user_channel(user_id),
        "notification.created",
        {"id": row.id, "kind": kind, "title": title, "unread": unread},
    )
    await _maybe_email(session, user_id, kind, title, body, subject_type, subject_id)
    return row


async def preferences_for(session: AsyncSession, user_id: str) -> list[dict]:
    """Every known kind with the stored preference or its default."""
    res = await session.execute(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    stored = {p.kind: p for p in res.scalars()}
    out = []
    for kind in NOTIFICATION_KINDS:
        p = stored.get(kind)
        out.append(
            {
                "kind": kind,
                "in_app": p.in_app if p else True,
                "email": p.email if p else kind in EMAIL_BY_DEFAULT,
                "stored": p is not None,
            }
        )
    return out


async def _maybe_email(
    session: AsyncSession,
    user_id: str,
    kind: str,
    title: str,
    body: str | None,
    subject_type: str | None,
    subject_id: str | None,
) -> None:
    if get_settings().email_backend == "none":
        return
    pref = (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id, NotificationPreference.kind == kind
            )
        )
    ).scalar_one_or_none()
    wanted = pref.email if pref is not None else kind in EMAIL_BY_DEFAULT
    if not wanted:
        return
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return
    base = get_settings().public_url.rstrip("/")
    path = SUBJECT_PATHS.get(subject_type or "", "/me/notifications").format(id=subject_id or "")
    await send_templated(
        user.email,
        "notification",
        user.locale,
        name=user.display_name,
        title=title,
        body=body or "",
        url=f"{base}{path}",
        notification_kind=kind,
    )


async def unread_count(session: AsyncSession, user_id: str) -> int:
    res = await session.execute(
        select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(res.scalar_one())
