"""Admin-curated library of ancillary skills and MCP servers."""

from fastapi import APIRouter, Response, UploadFile
from sqlalchemy import select

from autoskill.api.v1.deps import AdminUser, CurrentUser, SessionDep
from autoskill.config import get_settings
from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, NotFound, ValidationFailed
from autoskill.models.skill_version import LibraryComponent
from autoskill.schemas.common import OkResponse
from autoskill.schemas.draft import LibraryComponentIn, LibraryComponentOut
from autoskill.services.library.artifacts import load_artifact, store_artifact

router = APIRouter(prefix="/library", tags=["library"])


@router.get("", response_model=list[LibraryComponentOut])
async def list_components(session: SessionDep, user: CurrentUser, include_disabled: bool = False):
    stmt = select(LibraryComponent)
    if not include_disabled or user.role.value != "admin":
        stmt = stmt.where(LibraryComponent.is_enabled.is_(True))
    res = await session.execute(stmt.order_by(LibraryComponent.kind, LibraryComponent.name))
    return res.scalars().all()


@router.post("", response_model=LibraryComponentOut, status_code=201)
async def create_component(body: LibraryComponentIn, session: SessionDep, admin: AdminUser):
    if (await session.execute(select(LibraryComponent.id).where(LibraryComponent.slug == body.slug))).first():
        raise Conflict("slug_taken")
    row = LibraryComponent(**body.model_dump(), added_by=admin.id)
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        "library.create",
        actor_user_id=admin.id,
        subject_type="library_component",
        subject_id=row.id,
        after={"slug": row.slug},
    )
    await session.commit()
    await session.refresh(row)
    return row


@router.put("/{component_id}", response_model=LibraryComponentOut)
async def update_component(component_id: str, body: LibraryComponentIn, session: SessionDep, admin: AdminUser):
    row = await session.get(LibraryComponent, component_id)
    if row is None:
        raise NotFound("component_not_found")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await record_audit(
        session, "library.update", actor_user_id=admin.id, subject_type="library_component", subject_id=row.id
    )
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{component_id}", response_model=OkResponse)
async def delete_component(component_id: str, session: SessionDep, admin: AdminUser):
    row = await session.get(LibraryComponent, component_id)
    if row is None:
        raise NotFound("component_not_found")
    await session.delete(row)
    await record_audit(
        session, "library.delete", actor_user_id=admin.id, subject_type="library_component", subject_id=component_id
    )
    await session.commit()
    return OkResponse()


@router.post("/{component_id}/artifact", response_model=LibraryComponentOut)
async def upload_artifact(component_id: str, file: UploadFile, session: SessionDep, admin: AdminUser):
    """Upload the package of a component (zip / wheel / tar.gz). It is then served in install bundles."""
    row = await session.get(LibraryComponent, component_id)
    if row is None:
        raise NotFound("component_not_found")
    limit = get_settings().library_artifact_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("artifact_too_large", max_mb=get_settings().library_artifact_max_mb)
    record = store_artifact(row, file.filename or f"{row.slug}.zip", data)
    if not row.source or not row.source.get("type"):
        row.source = {**(row.source or {}), "type": "package_upload"}
    await record_audit(
        session,
        "library.artifact",
        actor_user_id=admin.id,
        subject_type="library_component",
        subject_id=row.id,
        after={"filename": record["filename"], "sha256": record["sha256"], "size": record["size"]},
    )
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{component_id}/artifact", response_model=LibraryComponentOut)
async def delete_artifact(component_id: str, session: SessionDep, admin: AdminUser):
    row = await session.get(LibraryComponent, component_id)
    if row is None:
        raise NotFound("component_not_found")
    row.artifact = None
    await record_audit(
        session, "library.artifact_delete", actor_user_id=admin.id, subject_type="library_component", subject_id=row.id
    )
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/{component_id}/artifact")
async def download_artifact(component_id: str, session: SessionDep, user: CurrentUser):
    row = await session.get(LibraryComponent, component_id)
    if row is None:
        raise NotFound("component_not_found")
    record, data = load_artifact(row)
    return Response(
        content=data,
        media_type=record.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{record["filename"]}"'},
    )
