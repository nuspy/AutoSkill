"""The machine's LLM providers, configured by the administrator through llmswitch.

Everything here is administration of the server itself — local engines, API keys, subscriptions
reused from an already authenticated CLI — so every route is admin only. Keys go in and are
never given back: the state only says whether one exists.
"""

from fastapi import APIRouter

from autoskill.api.v1.deps import AdminUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.llm import switch
from autoskill.schemas.common import OkResponse
from autoskill.schemas.llmswitch import (
    LlmSwitchAssign,
    LlmSwitchModels,
    LlmSwitchProviderCreate,
    LlmSwitchProviderUpdate,
    LlmSwitchState,
    LlmSwitchTestResult,
)

router = APIRouter(prefix="/llmswitch", tags=["llmswitch"])


async def _state() -> LlmSwitchState:
    return LlmSwitchState.model_validate(await switch.state())


@router.get("", response_model=LlmSwitchState)
async def get_state(user: AdminUser):
    """Providers, types, assignments, subscription status and installed CLI agents."""
    return await _state()


@router.post("/providers", response_model=LlmSwitchState, status_code=201)
async def add_provider(body: LlmSwitchProviderCreate, session: SessionDep, user: AdminUser):
    try:
        pid = await switch.add_provider(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise ValidationFailed("unknown_provider_type", message=str(exc)) from exc
    await record_audit(
        session,
        "llmswitch.provider.create",
        actor_user_id=user.id,
        subject_type="llmswitch_provider",
        subject_id=pid,
        after={"type": body.type, "name": body.name, "model": body.model, "has_key": bool(body.api_key)},
    )
    await session.commit()
    return await _state()


@router.patch("/providers/{pid}", response_model=LlmSwitchState)
async def update_provider(pid: str, body: LlmSwitchProviderUpdate, session: SessionDep, user: AdminUser):
    # `exclude_unset` matters: a form saved without touching the key must not wipe it.
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return await _state()
    try:
        await switch.update_provider(pid, fields)
    except KeyError as exc:
        raise NotFound("llmswitch_provider_not_found", provider=pid) from exc
    await record_audit(
        session,
        "llmswitch.provider.update",
        actor_user_id=user.id,
        subject_type="llmswitch_provider",
        subject_id=pid,
        after={k: ("***" if k == "api_key" else v) for k, v in fields.items()},
    )
    await session.commit()
    return await _state()


@router.delete("/providers/{pid}", response_model=LlmSwitchState)
async def remove_provider(pid: str, session: SessionDep, user: AdminUser):
    await switch.remove_provider(pid)
    await record_audit(
        session,
        "llmswitch.provider.delete",
        actor_user_id=user.id,
        subject_type="llmswitch_provider",
        subject_id=pid,
    )
    await session.commit()
    return await _state()


@router.get("/providers/{pid}/models", response_model=LlmSwitchModels)
async def list_models(pid: str, user: AdminUser, refresh: bool = False):
    """What this provider can serve. Local engines mark what is already in memory."""
    try:
        return LlmSwitchModels(models=await switch.models(pid, force=refresh))
    except KeyError as exc:
        raise NotFound("llmswitch_provider_not_found", provider=pid) from exc
    except Exception as exc:  # noqa: BLE001 - a provider that is down is an answer, not a crash
        return LlmSwitchModels(error=str(exc)[:300])


@router.post("/providers/{pid}/test", response_model=LlmSwitchTestResult)
async def test_provider(pid: str, user: AdminUser):
    """Reach the provider and count what it offers. An unreachable one answers, it does not raise."""
    result = await switch.test(pid)
    return LlmSwitchTestResult(
        ok=bool(result.get("ok")),
        models=int(result.get("models") or 0),
        sample=list(result.get("sample") or []),
        error=str(result.get("error") or ""),
    )


@router.post("/assign", response_model=LlmSwitchState)
async def assign(body: LlmSwitchAssign, session: SessionDep, user: AdminUser):
    """Point one purpose (or `default`) at a provider; `provider: null` detaches it."""
    try:
        await switch.assign(body.purpose, body.provider or None)
    except KeyError as exc:
        raise NotFound("llmswitch_provider_not_found", provider=body.provider or "") from exc
    except ValueError as exc:
        raise ValidationFailed("unknown_purpose", message=str(exc), purposes=list(switch.CONSUMERS)) from exc
    await record_audit(
        session,
        "llmswitch.assign",
        actor_user_id=user.id,
        subject_type="llmswitch_assignment",
        subject_id=body.purpose,
        after={"provider": body.provider},
    )
    await session.commit()
    return await _state()


@router.post("/reload", response_model=OkResponse)
async def reload_registry(user: AdminUser):
    """Re-read the registry file after it was edited outside the application."""
    switch.reset_registry()
    return OkResponse()
