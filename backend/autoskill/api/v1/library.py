"""Admin-curated library of ancillary skills and MCP servers."""

from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import AdminUser, CurrentUser, SessionDep
from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, NotFound
from autoskill.models.skill_version import LibraryComponent
from autoskill.schemas.common import OkResponse
from autoskill.schemas.draft import LibraryComponentIn, LibraryComponentOut

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
