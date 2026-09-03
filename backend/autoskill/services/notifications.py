"""Create notifications and push them to the user's SSE channel."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.events import emit, user_channel
from autoskill.models.notification import Notification


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
    return row


async def unread_count(session: AsyncSession, user_id: str) -> int:
    res = await session.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )
    return int(res.scalar_one())
