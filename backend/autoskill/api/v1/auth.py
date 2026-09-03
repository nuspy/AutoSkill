"""Registration, login, refresh cookies, device-code flow for the CLI."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.config import get_settings
from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from autoskill.core.security import (
    create_access_token,
    generate_api_key,
    generate_opaque_token,
    generate_user_code,
    hash_password,
    hash_token,
    verify_password,
)
from autoskill.db.base import utcnow
from autoskill.models.api_key import SCOPE_TELEMETRY_WRITE, SCOPE_TRIAL_CLIENT, ApiKey
from autoskill.models.device import Device, DeviceAuthorization
from autoskill.models.user import RefreshToken, User, UserRole
from autoskill.schemas.auth import (
    DeviceConfirmRequest,
    DevicePendingOut,
    DeviceStartRequest,
    DeviceStartResponse,
    DeviceTokenRequest,
    DeviceTokenResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from autoskill.schemas.common import OkResponse
from autoskill.schemas.user import UserOut
from autoskill.services.settings import get_setting

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "autoskill_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


async def _issue_tokens(
    session, user: User, response: Response, request: Request
) -> TokenResponse:
    settings = get_settings()
    raw = generate_opaque_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )
    )
    user.last_login_at = utcnow()
    await session.commit()
    _set_refresh_cookie(response, raw)
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, session: SessionDep, response: Response, request: Request):
    count = (await session.execute(select(func.count(User.id)))).scalar_one()
    if count > 0 and not await get_setting(session, "registration_open"):
        raise Forbidden("registration_closed")
    existing = await session.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise Conflict("email_taken")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        locale=body.locale,
        role=UserRole.admin if count == 0 else UserRole.member,
    )
    session.add(user)
    await session.flush()
    await record_audit(
        session, "user.register", actor_user_id=user.id, subject_type="user", subject_id=user.id
    )
    return await _issue_tokens(session, user, response, request)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: SessionDep, response: Response, request: Request):
    res = await session.execute(select(User).where(User.email == body.email.lower()))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise Unauthorized("invalid_credentials")
    if not user.is_active:
        raise Forbidden("user_disabled")
    await record_audit(session, "user.login", actor_user_id=user.id)
    return await _issue_tokens(session, user, response, request)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(session: SessionDep, response: Response, request: Request):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise Unauthorized("no_refresh_token")
    res = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )
    token = res.scalar_one_or_none()
    if token is None or token.revoked_at is not None or token.expires_at < utcnow():
        raise Unauthorized("invalid_refresh_token")
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("invalid_refresh_token")
    token.revoked_at = utcnow()  # rotation
    return await _issue_tokens(session, user, response, request)


@router.post("/logout", response_model=OkResponse)
async def logout(session: SessionDep, response: Response, request: Request):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        res = await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
        token = res.scalar_one_or_none()
        if token is not None:
            token.revoked_at = utcnow()
            await session.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return OkResponse()


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


# --- device-code flow (CLI login) -------------------------------------------------------


@router.post("/device", response_model=DeviceStartResponse)
async def device_start(body: DeviceStartRequest, session: SessionDep):
    settings = get_settings()
    device_code = generate_opaque_token(32)
    user_code = generate_user_code()
    session.add(
        DeviceAuthorization(
            device_code_hash=hash_token(device_code),
            user_code=user_code,
            device_name=body.device_name,
            device_os=body.device_os,
            agent_targets=body.agent_targets,
            expires_at=utcnow() + timedelta(minutes=settings.device_code_minutes),
            created_at=utcnow(),
        )
    )
    await session.commit()
    return DeviceStartResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=f"{settings.public_url.rstrip('/')}/device",
        expires_in=settings.device_code_minutes * 60,
    )


@router.post("/device/token", response_model=DeviceTokenResponse)
async def device_token(body: DeviceTokenRequest, session: SessionDep):
    res = await session.execute(
        select(DeviceAuthorization).where(
            DeviceAuthorization.device_code_hash == hash_token(body.device_code)
        )
    )
    auth = res.scalar_one_or_none()
    if auth is None:
        raise NotFound("device_code_not_found")
    if auth.status == "pending" and auth.expires_at < utcnow():
        auth.status = "expired"
        await session.commit()
    if auth.status != "approved":
        return DeviceTokenResponse(status=auth.status)
    key = auth.issued_key
    auth.issued_key = None  # one-time delivery
    auth.status = "consumed"
    await session.commit()
    device_id = None
    if auth.api_key_id:
        api_key = await session.get(ApiKey, auth.api_key_id)
        device_id = api_key.device_id if api_key else None
    return DeviceTokenResponse(
        status="approved", api_key=key, device_id=device_id, server_url=get_settings().public_url
    )


@router.get("/device/pending/{user_code}", response_model=DevicePendingOut)
async def device_pending(user_code: str, session: SessionDep, user: CurrentUser):
    auth = await _pending_auth(session, user_code)
    return DevicePendingOut(
        user_code=auth.user_code,
        device_name=auth.device_name,
        device_os=auth.device_os,
        agent_targets=auth.agent_targets,
        expires_at=auth.expires_at.isoformat(),
    )


async def _pending_auth(session, user_code: str) -> DeviceAuthorization:
    res = await session.execute(
        select(DeviceAuthorization).where(DeviceAuthorization.user_code == user_code.upper().strip())
    )
    auth = res.scalar_one_or_none()
    if auth is None or auth.status != "pending":
        raise NotFound("device_request_not_found")
    if auth.expires_at < utcnow():
        auth.status = "expired"
        await session.commit()
        raise ValidationFailed("device_request_expired")
    return auth


@router.post("/device/confirm", response_model=OkResponse)
async def device_confirm(body: DeviceConfirmRequest, session: SessionDep, user: CurrentUser):
    auth = await _pending_auth(session, body.user_code)
    if not body.approve:
        auth.status = "denied"
        await session.commit()
        return OkResponse()
    device = Device(
        user_id=user.id,
        name=auth.device_name,
        os=auth.device_os,
        agent_targets=auth.agent_targets,
        last_seen_at=utcnow(),
    )
    session.add(device)
    await session.flush()
    full, prefix, digest = generate_api_key()
    key = ApiKey(
        name=f"cli:{auth.device_name}",
        user_id=user.id,
        device_id=device.id,
        key_prefix=prefix,
        key_hash=digest,
        scopes=[SCOPE_TRIAL_CLIENT, SCOPE_TELEMETRY_WRITE],
    )
    session.add(key)
    await session.flush()
    auth.status = "approved"
    auth.user_id = user.id
    auth.api_key_id = key.id
    auth.issued_key = full
    await record_audit(
        session, "device.authorized", actor_user_id=user.id, subject_type="device", subject_id=device.id
    )
    await session.commit()
    return OkResponse()
