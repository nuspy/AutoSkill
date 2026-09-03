"""Skill Hub: shared catalog of published skills, favorites, installations, forks, categories."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from autoskill.api.v1.deps import AdminUser, AnyAuthUser, CurrentUser, SessionDep, get_optional_user
from autoskill.api.v1.skills import get_skill_for
from autoskill.config import get_settings
from autoskill.core.audit import record_audit
from autoskill.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from autoskill.core.permissions import require_project_role
from autoskill.db.base import utcnow
from autoskill.models.hub import Category, Favorite, Installation, SkillRepo
from autoskill.models.memory import SkillMemoryEntry
from autoskill.models.project import Project, ProjectRole
from autoskill.models.skill import VISIBILITIES, Skill
from autoskill.models.skill_version import SkillDependency, SkillVersion
from autoskill.models.user import User
from autoskill.schemas.common import OkResponse
from autoskill.schemas.hub import (
    CategoryIn,
    CategoryOut,
    ForkIn,
    HubHome,
    HubSearch,
    HubSkill,
    HubSkillDetail,
    InstallationIn,
    InstallationOut,
    SkillPublishSettings,
)
from autoskill.schemas.skill import SkillOut
from autoskill.services.distribution.install_tracking import mark_removed, record_installation
from autoskill.services.hub import catalog
from autoskill.services.hub.fork import fork_skill
from autoskill.services.packaging.store import load_package
from autoskill.services.settings import get_setting
from autoskill.services.targets import list_targets

router = APIRouter(tags=["hub"])


async def hub_viewer(session: SessionDep, user: Annotated[User | None, Depends(get_optional_user)]) -> User | None:
    if user is None and not await get_setting(session, "public_hub"):
        raise Forbidden("login_required")
    return user


HubViewer = Annotated[User | None, Depends(hub_viewer)]


async def _to_hub(session, skills: list[Skill], user: User | None) -> list[HubSkill]:
    favs = await catalog.favorite_ids(session, user)
    cats = {c.id: c.slug for c in await catalog.categories(session)}
    out: list[HubSkill] = []
    for s in skills:
        version = await catalog.published_version(session, s)
        project = await session.get(Project, s.project_id)
        item = HubSkill.model_validate(s)
        item.published_version = version.version if version else None
        item.published_version_id = version.id if version else None
        item.category_slug = cats.get(s.category_id) if s.category_id else None
        item.is_favorite = s.id in favs
        item.project_slug = project.slug if project else ""
        out.append(item)
    return out


async def _categories(session, user) -> list[CategoryOut]:
    counts = await catalog.category_counts(session, user)
    items = []
    for c in await catalog.categories(session):
        o = CategoryOut.model_validate(c)
        o.count = counts.get(c.id, 0)
        items.append(o)
    return items


@router.get("/hub", response_model=HubHome)
async def home(session: SessionDep, user: HubViewer):
    return HubHome(
        featured=await _to_hub(session, await catalog.featured(session, user), user),
        latest=await _to_hub(session, await catalog.latest(session, user), user),
        most_installed=await _to_hub(session, await catalog.most_installed(session, user), user),
        categories=await _categories(session, user),
        public=bool(await get_setting(session, "public_hub")),
    )


@router.get("/hub/search", response_model=HubSearch)
async def search(
    session: SessionDep,
    user: HubViewer,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    sort: str = "published",
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    category_id = None
    if category:
        cat = (await session.execute(select(Category).where(Category.slug == category))).scalar_one_or_none()
        category_id = cat.id if cat else "-"
    items, total = await catalog.search(
        session, user, q=q, category_id=category_id, tag=tag, sort=sort, limit=limit, offset=offset
    )
    return HubSearch(items=await _to_hub(session, items, user), total=total)


@router.get("/hub/categories", response_model=list[CategoryOut])
async def list_categories(session: SessionDep, user: HubViewer):
    return await _categories(session, user)


async def _visible_skill(session, skill_id: str, user: User | None) -> Skill:
    skill = await session.get(Skill, skill_id)
    if skill is None or skill.archived_at is not None:
        raise NotFound("skill_not_found")
    if skill.current_published_version_id and (
        skill.visibility == "public" or (skill.visibility == "shared" and user is not None)
    ):
        return skill
    if user is not None:
        try:
            await require_project_role(session, skill.project_id, user, ProjectRole.viewer)
            return skill
        except Forbidden:
            pass
    raise NotFound("skill_not_found")


@router.get("/hub/skills/{skill_id}", response_model=HubSkillDetail)
async def detail(skill_id: str, session: SessionDep, user: HubViewer):
    skill = await _visible_skill(session, skill_id, user)
    version = await catalog.published_version(session, skill)
    readme = load_package(skill.name, version).body() if version else ""
    versions = (
        (
            await session.execute(
                select(SkillVersion)
                .where(
                    SkillVersion.skill_id == skill.id, SkillVersion.state.in_(("published", "superseded", "deprecated"))
                )
                .order_by(SkillVersion.major.desc(), SkillVersion.minor.desc(), SkillVersion.patch.desc())
            )
        )
        .scalars()
        .all()
    )
    deps = (
        (await session.execute(select(SkillDependency).where(SkillDependency.skill_version_id == version.id)))
        .scalars()
        .all()
        if version
        else []
    )
    memory = (
        (
            await session.execute(
                select(SkillMemoryEntry)
                .where(
                    SkillMemoryEntry.skill_id == skill.id,
                    SkillMemoryEntry.status == "active",
                    SkillMemoryEntry.kind.in_(("business_need", "rationale", "integration_note")),
                )
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    repo = await session.get(SkillRepo, skill.id)
    project = await session.get(Project, skill.project_id)
    settings = get_settings()
    my_inst = None
    if user is not None:
        inst = (
            (
                await session.execute(
                    select(Installation)
                    .where(
                        Installation.user_id == user.id,
                        Installation.skill_id == skill.id,
                        Installation.state != "removed",
                    )
                    .order_by(Installation.updated_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if inst is not None:
            my_inst = InstallationOut.model_validate(inst).model_dump()
    hub = (await _to_hub(session, [skill], user))[0]
    return HubSkillDetail(
        skill=hub,
        readme=readme,
        versions=[
            {
                "id": v.id,
                "version": v.version,
                "state": v.state,
                "changelog": v.changelog,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
        install_targets=list_targets(),
        dependencies=[{"component_slug": d.component_slug, "reason": d.reason} for d in deps],
        memory_public=[{"kind": m.kind, "title": m.title, "body": m.body} for m in memory],
        git_url=f"{settings.public_url}/git/{project.slug}/{skill.name}.git" if repo and project else None,
        zip_url=f"{settings.public_url}/api/v1/versions/{version.id}/package.zip" if version else None,
        my_installation=my_inst,
    )


# --- favorites -------------------------------------------------------------------------


@router.get("/me/favorites", response_model=list[HubSkill])
async def favorites(session: SessionDep, user: CurrentUser):
    res = await session.execute(
        select(Skill)
        .join(Favorite, Favorite.skill_id == Skill.id)
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
    )
    return await _to_hub(session, list(res.scalars()), user)


@router.post("/me/favorites/{skill_id}", response_model=OkResponse)
async def add_favorite(skill_id: str, session: SessionDep, user: CurrentUser):
    await _visible_skill(session, skill_id, user)
    exists = (
        await session.execute(select(Favorite).where(Favorite.user_id == user.id, Favorite.skill_id == skill_id))
    ).scalar_one_or_none()
    if exists is None:
        session.add(Favorite(user_id=user.id, skill_id=skill_id, created_at=utcnow()))
        await session.commit()
    return OkResponse()


@router.delete("/me/favorites/{skill_id}", response_model=OkResponse)
async def remove_favorite(skill_id: str, session: SessionDep, user: CurrentUser):
    row = (
        await session.execute(select(Favorite).where(Favorite.user_id == user.id, Favorite.skill_id == skill_id))
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return OkResponse()


# --- installations ---------------------------------------------------------------------


async def _installation_out(session, inst: Installation) -> InstallationOut:
    skill = await session.get(Skill, inst.skill_id)
    version = await session.get(SkillVersion, inst.skill_version_id)
    latest = await catalog.published_version(session, skill) if skill else None
    out = InstallationOut.model_validate(inst)
    out.skill_title = skill.title if skill else ""
    out.skill_name = skill.name if skill else ""
    out.installed_version = version.version if version else ""
    out.latest_version = latest.version if latest else None
    out.latest_version_id = latest.id if latest else None
    out.update_available = bool(latest and latest.id != inst.skill_version_id)
    return out


@router.get("/me/installations", response_model=list[InstallationOut])
async def my_installations(session: SessionDep, user: AnyAuthUser):
    res = await session.execute(
        select(Installation)
        .where(Installation.user_id == user.id, Installation.state != "removed")
        .order_by(Installation.updated_at.desc())
    )
    return [await _installation_out(session, i) for i in res.scalars()]


@router.post("/me/installations", response_model=InstallationOut, status_code=201)
async def register_installation(body: InstallationIn, session: SessionDep, user: AnyAuthUser):
    version = await session.get(SkillVersion, body.skill_version_id)
    if version is None:
        raise NotFound("version_not_found")
    await _visible_skill(session, version.skill_id, user)
    inst = await record_installation(
        session,
        user_id=user.id,
        skill_id=version.skill_id,
        skill_version_id=version.id,
        target_agent=body.target_agent,
        channel=body.channel,
        kind=body.kind,
        device_id=body.device_id,
        state=body.state,
    )
    await session.commit()
    await session.refresh(inst)
    return await _installation_out(session, inst)


@router.delete("/me/installations/{installation_id}", response_model=OkResponse)
async def remove_installation(installation_id: str, session: SessionDep, user: AnyAuthUser):
    inst = await session.get(Installation, installation_id)
    if inst is None or inst.user_id != user.id:
        raise NotFound("installation_not_found")
    await mark_removed(session, inst)
    await session.commit()
    return OkResponse()


# --- fork and publish settings ---------------------------------------------------------


@router.post("/skills/{skill_id}/fork", response_model=SkillOut, status_code=201)
async def fork(skill_id: str, body: ForkIn, session: SessionDep, user: CurrentUser):
    source = await _visible_skill(session, skill_id, user)
    await require_project_role(session, body.target_project_id, user, ProjectRole.editor)
    version = await catalog.published_version(session, source)
    if version is None:
        version = await session.get(SkillVersion, source.latest_version_id) if source.latest_version_id else None
    if version is None:
        raise Conflict("nothing_to_fork")
    skill, _ = await fork_skill(
        session,
        source=source,
        source_version=version,
        target_project_id=body.target_project_id,
        actor=user,
        new_title=body.title,
    )
    await record_audit(
        session,
        "skill.fork",
        actor_user_id=user.id,
        project_id=body.target_project_id,
        subject_type="skill",
        subject_id=skill.id,
        after={"from": source.id},
    )
    await session.commit()
    await session.refresh(skill)
    return SkillOut.model_validate(skill)


@router.patch("/skills/{skill_id}/publish-settings", response_model=SkillOut)
async def publish_settings(skill_id: str, body: SkillPublishSettings, session: SessionDep, user: CurrentUser):
    skill = await get_skill_for(session, skill_id, user, ProjectRole.owner)
    if body.visibility is not None:
        if body.visibility not in VISIBILITIES:
            raise ValidationFailed("unknown_visibility")
        skill.visibility = body.visibility
        repo = await session.get(SkillRepo, skill.id)
        if repo is not None:
            repo.public_clone = body.visibility == "public"
    if body.category_id is not None:
        skill.category_id = body.category_id or None
    if body.tags is not None:
        skill.tags = [t.strip().lower() for t in body.tags if t.strip()][:20]
    await session.commit()
    await session.refresh(skill)
    return SkillOut.model_validate(skill)


# --- admin -----------------------------------------------------------------------------


@router.post("/admin/hub/categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryIn, session: SessionDep, admin: AdminUser):
    if (await session.execute(select(Category).where(Category.slug == body.slug))).scalar_one_or_none():
        raise Conflict("slug_taken")
    row = Category(**body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return CategoryOut.model_validate(row)


@router.put("/admin/hub/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: str, body: CategoryIn, session: SessionDep, admin: AdminUser):
    row = await session.get(Category, category_id)
    if row is None:
        raise NotFound("category_not_found")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return CategoryOut.model_validate(row)


@router.delete("/admin/hub/categories/{category_id}", response_model=OkResponse)
async def delete_category(category_id: str, session: SessionDep, admin: AdminUser):
    row = await session.get(Category, category_id)
    if row is not None:
        res = await session.execute(select(Skill).where(Skill.category_id == category_id))
        for s in res.scalars():
            s.category_id = None
        await session.delete(row)
        await session.commit()
    return OkResponse()


@router.post("/admin/hub/skills/{skill_id}/feature", response_model=SkillOut)
async def feature(skill_id: str, session: SessionDep, admin: AdminUser, featured: bool = True):
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise NotFound("skill_not_found")
    skill.is_featured = featured
    skill.featured_at = utcnow() if featured else None
    await record_audit(
        session,
        "hub.feature" if featured else "hub.unfeature",
        actor_user_id=admin.id,
        subject_type="skill",
        subject_id=skill.id,
    )
    await session.commit()
    await session.refresh(skill)
    return SkillOut.model_validate(skill)


@router.get("/admin/hub/skills", response_model=list[HubSkill])
async def all_published(session: SessionDep, admin: AdminUser):
    res = await session.execute(
        select(Skill)
        .where(Skill.current_published_version_id.is_not(None), Skill.archived_at.is_(None))
        .order_by(Skill.published_at.desc())
    )
    return await _to_hub(session, list(res.scalars()), admin)
