"""LLM provider configuration (system scope for admins, project scope for owners)."""

import time

from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.crypto import encrypt
from autoskill.core.errors import Forbidden, NotFound, ValidationFailed
from autoskill.core.permissions import is_admin, require_project_role
from autoskill.llm.provider import ChatMessage, ChatRequest, LlmError
from autoskill.llm.registry import build_provider
from autoskill.models.llm_provider import ADAPTERS, PURPOSES, LlmProvider
from autoskill.models.project import ProjectRole
from autoskill.schemas.common import OkResponse
from autoskill.schemas.llm_provider import ProviderCreate, ProviderOut, ProviderTestResult, ProviderUpdate

router = APIRouter(tags=["providers"])


def _out(row: LlmProvider) -> ProviderOut:
    out = ProviderOut.model_validate(row)
    out.has_api_key = bool(row.api_key_encrypted)
    return out


def _validate(body: ProviderCreate | ProviderUpdate) -> None:
    adapter = getattr(body, "adapter", None)
    if adapter is not None and adapter not in ADAPTERS:
        raise ValidationFailed("unknown_adapter", adapters=list(ADAPTERS))
    purposes = getattr(body, "purposes", None)
    if purposes:
        bad = set(purposes) - set(PURPOSES)
        if bad:
            raise ValidationFailed("unknown_purposes", purposes=sorted(bad))


async def _authorize(session, user, scope: str, project_id: str | None) -> None:
    if scope == "system":
        if not is_admin(user):
            raise Forbidden("admin_required")
    else:
        if not project_id:
            raise ValidationFailed("project_required")
        await require_project_role(session, project_id, user, ProjectRole.owner)


async def _clear_default(session, scope: str, project_id: str | None) -> None:
    res = await session.execute(
        select(LlmProvider).where(
            LlmProvider.scope == scope, LlmProvider.project_id == project_id, LlmProvider.is_default.is_(True)
        )
    )
    for row in res.scalars():
        row.is_default = False


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(session: SessionDep, user: CurrentUser, project_id: str | None = None):
    """System providers (visible to everyone, keys hidden) plus the project's own when requested."""
    stmt = select(LlmProvider).where(LlmProvider.scope == "system")
    rows = list((await session.execute(stmt)).scalars().all())
    if project_id:
        await require_project_role(session, project_id, user, ProjectRole.viewer)
        res = await session.execute(select(LlmProvider).where(LlmProvider.project_id == project_id))
        rows.extend(res.scalars().all())
    return [_out(r) for r in rows]


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(body: ProviderCreate, session: SessionDep, user: CurrentUser, project_id: str | None = None):
    _validate(body)
    scope = "project" if project_id else "system"
    await _authorize(session, user, scope, project_id)
    if body.is_default:
        await _clear_default(session, scope, project_id)
    row = LlmProvider(
        scope=scope,
        project_id=project_id,
        name=body.name,
        adapter=body.adapter,
        model=body.model,
        base_url=body.base_url,
        api_key_encrypted=encrypt(body.api_key) if body.api_key else None,
        purposes=body.purposes,
        extra=body.extra,
        is_default=body.is_default,
        is_enabled=body.is_enabled,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        "provider.create",
        actor_user_id=user.id,
        project_id=project_id,
        subject_type="provider",
        subject_id=row.id,
        after={"name": row.name, "adapter": row.adapter, "model": row.model},
    )
    await session.commit()
    await session.refresh(row)
    return _out(row)


async def _get(session, user, provider_id: str) -> LlmProvider:
    row = await session.get(LlmProvider, provider_id)
    if row is None:
        raise NotFound("provider_not_found")
    await _authorize(session, user, row.scope, row.project_id)
    return row


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(provider_id: str, body: ProviderUpdate, session: SessionDep, user: CurrentUser):
    _validate(body)
    row = await _get(session, user, provider_id)
    data = body.model_dump(exclude_unset=True)
    if data.pop("api_key", None):
        row.api_key_encrypted = encrypt(body.api_key)  # type: ignore[arg-type]
    if data.get("is_default"):
        await _clear_default(session, row.scope, row.project_id)
    for key, value in data.items():
        setattr(row, key, value)
    await record_audit(
        session,
        "provider.update",
        actor_user_id=user.id,
        project_id=row.project_id,
        subject_type="provider",
        subject_id=row.id,
        after={k: v for k, v in data.items() if k != "api_key"},
    )
    await session.commit()
    await session.refresh(row)
    return _out(row)


@router.delete("/providers/{provider_id}", response_model=OkResponse)
async def delete_provider(provider_id: str, session: SessionDep, user: CurrentUser):
    row = await _get(session, user, provider_id)
    await record_audit(
        session,
        "provider.delete",
        actor_user_id=user.id,
        project_id=row.project_id,
        subject_type="provider",
        subject_id=row.id,
    )
    await session.delete(row)
    await session.commit()
    return OkResponse()


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(provider_id: str, session: SessionDep, user: CurrentUser):
    row = await _get(session, user, provider_id)
    provider = build_provider(row)
    started = time.monotonic()
    try:
        res = await provider.chat(
            ChatRequest(
                messages=[ChatMessage(role="user", content="Reply with the single word OK.")],
                max_tokens=5,
                temperature=0,
            )
        )
    except LlmError as exc:
        row.health = {"ok": False, "message": str(exc)[:500]}
        await session.commit()
        return ProviderTestResult(ok=False, message=str(exc)[:500])
    latency = int((time.monotonic() - started) * 1000)
    models: list[str] = []
    if hasattr(provider, "list_models"):
        try:
            models = await provider.list_models()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            models = []
    caps = {"tools": provider.capabilities.tools, "json_schema": provider.capabilities.json_schema}
    row.health = {"ok": True, "latency_ms": latency, "reply": res.text[:50]}
    if models:
        row.models = models[:200]
    await session.commit()
    return ProviderTestResult(
        ok=True, message=res.text[:200] or "ok", latency_ms=latency, models=models[:200], capabilities=caps
    )
