from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.core.permissions import require_project_role
from autoskill.models.data_source import DATA_SOURCE_KINDS, SENSITIVITIES, DataSource
from autoskill.models.project import ProjectRole
from autoskill.schemas.common import OkResponse
from autoskill.schemas.data_source import DataSourceCreate, DataSourceOut, DataSourceUpdate

router = APIRouter(prefix="/projects/{project_id}/data-sources", tags=["data-sources"])


@router.get("", response_model=list[DataSourceOut])
async def list_sources(project_id: str, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.viewer)
    res = await session.execute(select(DataSource).where(DataSource.project_id == project_id).order_by(DataSource.name))
    return res.scalars().all()


@router.post("", response_model=DataSourceOut, status_code=201)
async def create_source(project_id: str, body: DataSourceCreate, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.editor)
    if body.kind not in DATA_SOURCE_KINDS:
        raise ValidationFailed("unknown_kind", kinds=list(DATA_SOURCE_KINDS))
    if body.sensitivity not in SENSITIVITIES:
        raise ValidationFailed("unknown_sensitivity")
    row = DataSource(
        project_id=project_id,
        name=body.name,
        kind=body.kind,
        description=body.description,
        access_notes=body.access_notes,
        schema_def=body.schema_def,
        sensitivity=body.sensitivity,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _get(session, project_id: str, source_id: str) -> DataSource:
    row = await session.get(DataSource, source_id)
    if row is None or row.project_id != project_id:
        raise NotFound("data_source_not_found")
    return row


@router.patch("/{source_id}", response_model=DataSourceOut)
async def update_source(
    project_id: str, source_id: str, body: DataSourceUpdate, session: SessionDep, user: CurrentUser
):
    await require_project_role(session, project_id, user, ProjectRole.editor)
    row = await _get(session, project_id, source_id)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{source_id}", response_model=OkResponse)
async def delete_source(project_id: str, source_id: str, session: SessionDep, user: CurrentUser):
    await require_project_role(session, project_id, user, ProjectRole.editor)
    row = await _get(session, project_id, source_id)
    await session.delete(row)
    await session.commit()
    return OkResponse()
