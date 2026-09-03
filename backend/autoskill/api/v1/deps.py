"""FastAPI dependencies: database session, current user, API key auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.core.errors import Forbidden, Unauthorized
from autoskill.core.security import decode_access_token, hash_token
from autoskill.db.base import utcnow
from autoskill.db.session import get_session
from autoskill.models.api_key import ApiKey
from autoskill.models.user import User, UserRole

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # EventSource cannot set headers: allow the access token as a query parameter for SSE.
    query_token = request.query_params.get("access_token")
    if query_token and request.url.path.endswith("/events"):
        return query_token
    return None


async def get_optional_user(request: Request, session: SessionDep) -> User | None:
    token = _bearer(request)
    if token is None or token.startswith("ask_"):
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user = await session.get(User, payload["sub"])
    if user is None or not user.is_active:
        return None
    return user


async def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise Unauthorized("not_authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin_user(user: CurrentUser) -> User:
    if user.role != UserRole.admin:
        raise Forbidden("admin_required")
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]


async def get_reviewer_user(user: CurrentUser) -> User:
    if user.role not in (UserRole.admin, UserRole.reviewer):
        raise Forbidden("reviewer_required")
    return user


ReviewerUser = Annotated[User, Depends(get_reviewer_user)]


async def get_api_key(request: Request, session: SessionDep) -> ApiKey:
    token = _bearer(request) or request.headers.get("x-api-key")
    if not token or not token.startswith("ask_"):
        raise Unauthorized("api_key_required")
    res = await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_token(token)))
    key = res.scalar_one_or_none()
    now = utcnow()
    if key is None or key.revoked_at is not None or (key.expires_at and key.expires_at < now):
        raise Unauthorized("invalid_api_key")
    key.last_used_at = now
    return key


ApiKeyDep = Annotated[ApiKey, Depends(get_api_key)]


def require_scope(key: ApiKey, scope: str) -> None:
    if scope not in (key.scopes or []):
        raise Forbidden("missing_scope", scope=scope)


async def get_user_from_api_key(key: ApiKeyDep, session: SessionDep) -> User:
    """Resolve the user behind a user-owned API key (CLI/device flows)."""
    if key.user_id is None:
        raise Forbidden("user_key_required")
    user = await session.get(User, key.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("invalid_api_key")
    return user


async def get_user_any_auth(
    request: Request,
    session: SessionDep,
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """Accept either a JWT session or a user API key."""
    if user is not None:
        return user
    key = await get_api_key(request, session)
    return await get_user_from_api_key(key, session)


AnyAuthUser = Annotated[User, Depends(get_user_any_auth)]
