from fastapi import APIRouter

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.core.errors import NotFound, ValidationFailed
from autoskill.models.memory import MEMORY_STATUSES, SkillMemoryEntry
from autoskill.models.project import ProjectRole
from autoskill.schemas.skill import MemoryEntryCreate, MemoryEntryOut, MemoryEntryUpdate
from autoskill.services.memory import store

router = APIRouter(prefix="/skills/{skill_id}/memory", tags=["memory"])


@router.get("", response_model=list[MemoryEntryOut])
async def list_memory(
    skill_id: str,
    session: SessionDep,
    user: CurrentUser,
    status: str | None = "active",
    kind: str | None = None,
    step_key: str | None = None,
):
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    if status == "all":
        status = None
    return await store.list_entries(session, skill_id, status=status, kind=kind, step_key=step_key)


@router.post("", response_model=MemoryEntryOut, status_code=201)
async def create_memory(skill_id: str, body: MemoryEntryCreate, session: SessionDep, user: CurrentUser):
    await get_skill_for(session, skill_id, user, ProjectRole.editor)
    entry = await store.add_entry(
        session,
        skill_id,
        kind=body.kind,
        title=body.title,
        body=body.body,
        structured=body.structured,
        step_key=body.step_key,
        source="manual",
        author_user_id=user.id,
        tags=body.tags,
    )
    await session.commit()
    await session.refresh(entry)
    return entry


@router.post("/{entry_id}/supersede", response_model=MemoryEntryOut)
async def supersede_memory(
    skill_id: str, entry_id: str, body: MemoryEntryUpdate, session: SessionDep, user: CurrentUser
):
    await get_skill_for(session, skill_id, user, ProjectRole.editor)
    old = await session.get(SkillMemoryEntry, entry_id)
    if old is None or old.skill_id != skill_id:
        raise NotFound("memory_entry_not_found")
    entry = await store.supersede(
        session, entry_id, title=body.title, body=body.body, structured=body.structured, author_user_id=user.id
    )
    await session.commit()
    await session.refresh(entry)
    return entry


@router.post("/{entry_id}/status/{status}", response_model=MemoryEntryOut)
async def set_memory_status(skill_id: str, entry_id: str, status: str, session: SessionDep, user: CurrentUser):
    await get_skill_for(session, skill_id, user, ProjectRole.editor)
    if status not in MEMORY_STATUSES:
        raise ValidationFailed("unknown_status")
    entry = await session.get(SkillMemoryEntry, entry_id)
    if entry is None or entry.skill_id != skill_id:
        raise NotFound("memory_entry_not_found")
    await store.set_status(session, entry_id, status)
    await session.commit()
    await session.refresh(entry)
    return entry
