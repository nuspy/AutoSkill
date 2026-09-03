from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.core.permissions import require_project_role
from autoskill.core.security import generate_api_key
from autoskill.db.base import utcnow
from autoskill.models.api_key import ALL_SCOPES, ApiKey
from autoskill.models.project import ProjectRole
from autoskill.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from autoskill.schemas.common import OkResponse

router = APIRouter(tags=["api-keys"])


@router.get("/projects/{project_id}/api-keys", response_model=list[ApiKeyOut])
async def list_project_keys(project_id: str, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.editor)
    res = await session.execute(
        select(ApiKey).where(ApiKey.project_id == project_id).order_by(ApiKey.created_at.desc())
    )
    return res.scalars().all()


@router.post("/projects/{project_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_project_key(
    project_id: str, body: ApiKeyCreate, session: SessionDep, user: CurrentUser
):
    await require_project_role(session, project_id, user, ProjectRole.owner)
    bad = set(body.scopes) - ALL_SCOPES
    if bad:
        raise ValidationFailed("unknown_scopes", scopes=sorted(bad))
    full, prefix, digest = generate_api_key()
    key = ApiKey(
        name=body.name,
        project_id=project_id,
        key_prefix=prefix,
        key_hash=digest,
        scopes=body.scopes,
        expires_at=utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None,
    )
    session.add(key)
    await session.flush()
    await record_audit(
        session, "api_key.create", actor_user_id=user.id, project_id=project_id,
        subject_type="api_key", subject_id=key.id, after={"name": key.name, "scopes": key.scopes},
    )
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=full)


@router.delete("/api-keys/{key_id}", response_model=OkResponse)
async def revoke_key(key_id: str, session: SessionDep, user: CurrentUser):
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFound("api_key_not_found")
    if key.project_id:
        await require_project_role(session, key.project_id, user, ProjectRole.owner)
    elif key.user_id != user.id and user.role.value != "admin":
        raise NotFound("api_key_not_found")
    key.revoked_at = utcnow()
    await record_audit(
        session, "api_key.revoke", actor_user_id=user.id, project_id=key.project_id,
        subject_type="api_key", subject_id=key.id,
    )
    await session.commit()
    return OkResponse()


@router.get("/me/api-keys", response_model=list[ApiKeyOut])
async def list_my_keys(session: SessionDep, user: CurrentUser):
    res = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    return res.scalars().all()
