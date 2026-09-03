"""Audit log writer."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.audit import AuditLog


async def record_audit(
    session: AsyncSession,
    action: str,
    *,
    actor_user_id: str | None = None,
    actor_api_key_id: str | None = None,
    project_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
        project_id=project_id,
        subject_type=subject_type,
        subject_id=subject_id,
        before=before,
        after=after,
        ip=ip,
    )
    session.add(entry)
    return entry
