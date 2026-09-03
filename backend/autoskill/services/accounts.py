"""Invitations and password resets: one-time emailed tokens (models.user.UserToken)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.config import get_settings
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.core.security import generate_opaque_token, hash_password, hash_token
from autoskill.db.base import utcnow
from autoskill.models.project import Project
from autoskill.models.user import RefreshToken, User, UserToken
from autoskill.services.email import send_templated


def _url(path: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}{path}"


async def create_invitation(
    session: AsyncSession,
    *,
    email: str,
    role: str,
    project_id: str | None,
    invited_by: User,
    expires_in_days: int = 7,
) -> tuple[UserToken, str]:
    email = email.lower().strip()
    if (await session.execute(select(User.id).where(User.email == email))).first():
        raise Conflict("email_taken", message="This person already has an account.")
    project = await session.get(Project, project_id) if project_id else None
    if project_id and project is None:
        raise NotFound("project_not_found")
    token = generate_opaque_token(24)
    row = UserToken(
        kind="invite",
        email=email,
        token_hash=hash_token(token),
        role=role,
        project_id=project_id,
        invited_by=invited_by.id,
        expires_at=utcnow() + timedelta(days=expires_in_days),
    )
    session.add(row)
    await session.flush()
    await send_templated(
        email,
        "invite",
        invited_by.locale,
        inviter=invited_by.display_name,
        project=project.name if project else "",
        url=_url(f"/invite/{token}"),
        expires=row.expires_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    return row, token


async def valid_token(session: AsyncSession, kind: str, token: str) -> UserToken:
    row = (
        await session.execute(
            select(UserToken).where(UserToken.token_hash == hash_token(token), UserToken.kind == kind)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("token_not_found")
    if row.used_at is not None:
        raise Conflict("token_used", message="This link was already used.")
    if row.expires_at < utcnow():
        raise ValidationFailed("token_expired", message="This link has expired.")
    return row


async def request_password_reset(session: AsyncSession, email: str) -> bool:
    """Always returns quietly; sends a reset link only when the account exists."""
    user = (await session.execute(select(User).where(User.email == email.lower().strip()))).scalar_one_or_none()
    if user is None or not user.is_active:
        return False
    token = generate_opaque_token(24)
    row = UserToken(
        kind="password_reset",
        email=user.email,
        token_hash=hash_token(token),
        user_id=user.id,
        expires_at=utcnow() + timedelta(hours=1),
    )
    session.add(row)
    await session.flush()
    await send_templated(user.email, "password_reset", user.locale, name=user.display_name, url=_url(f"/reset/{token}"))
    return True


async def reset_password(session: AsyncSession, token: str, new_password: str) -> User:
    row = await valid_token(session, "password_reset", token)
    user = await session.get(User, row.user_id) if row.user_id else None
    if user is None:
        raise NotFound("token_not_found")
    user.password_hash = hash_password(new_password)
    row.used_at = utcnow()
    res = await session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    )
    for rt in res.scalars():
        rt.revoked_at = utcnow()
    return user
