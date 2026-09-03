"""Skill Hub: shared catalog of published skills, favorites, installations, forks, categories."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from autoskill.api.v1.deps import AdminUser, AnyAuthUser, CurrentUser, SessionDep, get_optional_user
from autoskill.api.v1.skills import get_skill_for
from autoskill.config import get_settings
from autoskill.core.audit import record_audit
from autoskill.core.crypto import encrypt
from autoskill.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from autoskill.core.permissions import require_project_role
from autoskill.db.base import utcnow
from autoskill.models.hub import Category, Contribution, CuratedList, Favorite, Installation, SkillRepo
from autoskill.models.memory import SkillMemoryEntry
from autoskill.models.project import Project, ProjectRole
from autoskill.models.skill import VISIBILITIES, Skill
from autoskill.models.skill_version import SkillDependency, SkillVersion
from autoskill.models.user import User
from autoskill.schemas.common import OkResponse
from autoskill.schemas.hub import (
    CategoryIn,
    CategoryOut,
    ContributionDecision,
    ContributionIn,
    ContributionOut,
    CuratedListDetail,
    CuratedListIn,
    CuratedListOut,
    ForkIn,
    HubHome,
    HubSearch,
    HubSkill,
    HubSkillDetail,
    InstallationIn,
    InstallationOut,
    RatingIn,
    RatingOut,
    SkillPublishSettings,
)
from autoskill.schemas.skill import SkillOut
from autoskill.services.distribution import git_repo
from autoskill.services.distribution.install_tracking import mark_removed, record_installation
from autoskill.services.hub import catalog, contributions, lists, ratings
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


async def _lists_out(session, rows) -> list[CuratedListOut]:
    counts = await lists.item_counts(session)
    out = []
    for lst in rows:
        o = CuratedListOut.model_validate(lst)
        o.count = counts.get(lst.id, 0)
        out.append(o)
    return out


@router.get("/hub", response_model=HubHome)
async def home(session: SessionDep, user: HubViewer):
    return HubHome(
        featured=await _to_hub(session, await catalog.featured(session, user), user),
        latest=await _to_hub(session, await catalog.latest(session, user), user),
        most_installed=await _to_hub(session, await catalog.most_installed(session, user), user),
        top_rated=await _to_hub(session, await catalog.top_rated(session, user), user),
        categories=await _categories(session, user),
        lists=await _lists_out(session, await lists.public_lists(session)),
        public=bool(await get_setting(session, "public_hub")),
    )


@router.get("/hub/lists", response_model=list[CuratedListOut])
async def hub_lists(session: SessionDep, user: HubViewer):
    return await _lists_out(session, await lists.public_lists(session))


@router.get("/hub/lists/{slug}", response_model=CuratedListDetail)
async def hub_list(slug: str, session: SessionDep, user: HubViewer):
    lst = await lists.by_slug(session, slug)
    (out,) = await _lists_out(session, [lst])
    return CuratedListDetail(list=out, items=await _to_hub(session, await lists.skills_of(session, lst, user), user))


# --- ratings ----------------------------------------------------------------------------


async def _rating_out(session, r) -> RatingOut:
    o = RatingOut.model_validate(r)
    u = await session.get(User, r.user_id)
    o.user_name = u.display_name if u else ""
    return o


@router.get("/hub/skills/{skill_id}/ratings", response_model=list[RatingOut])
async def skill_ratings(skill_id: str, session: SessionDep, user: HubViewer):
    await _visible_skill(session, skill_id, user)
    return [await _rating_out(session, r) for r in await ratings.list_ratings(session, skill_id)]


@router.put("/hub/skills/{skill_id}/rating", response_model=RatingOut)
async def rate_skill(skill_id: str, body: RatingIn, session: SessionDep, user: CurrentUser):
    skill = await _visible_skill(session, skill_id, user)
    row = await ratings.rate(
        session,
        skill=skill,
        user_id=user.id,
        stars=body.stars,
        comment=body.comment,
        version_id=skill.current_published_version_id,
    )
    await session.commit()
    await session.refresh(row)
    return await _rating_out(session, row)


@router.delete("/hub/skills/{skill_id}/rating", response_model=OkResponse)
async def unrate_skill(skill_id: str, session: SessionDep, user: CurrentUser):
    skill = await _visible_skill(session, skill_id, user)
    await ratings.unrate(session, skill=skill, user_id=user.id)
    await session.commit()
    return OkResponse()


# --- contributions (variant -> original) -------------------------------------------------


async def _contribution_out(session, c) -> ContributionOut:
    o = ContributionOut.model_validate(c)
    src = await session.get(Skill, c.source_skill_id)
    tgt = await session.get(Skill, c.target_skill_id)
    ver = await session.get(SkillVersion, c.source_version_id)
    who = await session.get(User, c.proposed_by)
    o.source_title = src.title if src else ""
    o.source_version = ver.version if ver else ""
    o.target_title = tgt.title if tgt else ""
    o.proposed_by_name = who.display_name if who else ""
    return o


@router.post("/skills/{skill_id}/contribute", response_model=ContributionOut, status_code=201)
async def contribute(skill_id: str, body: ContributionIn, session: SessionDep, user: CurrentUser):
    """Propose the changes of a variant (fork) back to the original skill."""
    variant = await get_skill_for(session, skill_id, user, ProjectRole.editor)
    version = None
    if body.version_id:
        version = await session.get(SkillVersion, body.version_id)
    else:
        version = await catalog.published_version(session, variant)
        if version is None and variant.latest_version_id:
            version = await session.get(SkillVersion, variant.latest_version_id)
    if version is None:
        raise NotFound("version_not_found")
    row = await contributions.propose(session, variant=variant, version=version, actor=user, message=body.message)
    await record_audit(
        session,
        "skill.contribute",
        actor_user_id=user.id,
        subject_type="contribution",
        subject_id=row.id,
        after={"target_skill_id": row.target_skill_id},
    )
    await session.commit()
    await session.refresh(row)
    return await _contribution_out(session, row)


@router.get("/skills/{skill_id}/contributions", response_model=list[ContributionOut])
async def skill_contributions(skill_id: str, session: SessionDep, user: CurrentUser):
    """Contributions received by this skill and proposed by it (as a variant)."""
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    res = await session.execute(
        select(Contribution)
        .where(or_(Contribution.target_skill_id == skill_id, Contribution.source_skill_id == skill_id))
        .order_by(Contribution.created_at.desc())
    )
    return [await _contribution_out(session, c) for c in res.scalars()]


@router.post("/contributions/{contribution_id}/decision", response_model=ContributionOut)
async def decide_contribution(contribution_id: str, body: ContributionDecision, session: SessionDep, user: CurrentUser):
    row = await session.get(Contribution, contribution_id)
    if row is None:
        raise NotFound("contribution_not_found")
    await get_skill_for(session, row.target_skill_id, user, ProjectRole.editor)
    await contributions.decide(session, contribution=row, actor=user, accept=body.accept, comment=body.comment)
    await record_audit(
        session,
        "contribution.decide",
        actor_user_id=user.id,
        subject_type="contribution",
        subject_id=row.id,
        after={"state": row.state},
    )
    await session.commit()
    await session.refresh(row)
    return await _contribution_out(session, row)


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
    rating_rows = [await _rating_out(session, r) for r in await ratings.list_ratings(session, skill.id)]
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
        my_rating=next((r for r in rating_rows if user and r.user_id == user.id), None),
        ratings=rating_rows[:20],
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
    if body.external_remote_url is not None or body.external_token is not None:
        repo = await session.get(SkillRepo, skill.id)
        if repo is None:
            repo = SkillRepo(
                skill_id=skill.id,
                path=str(git_repo.repo_path((await session.get(Project, skill.project_id)).slug, skill.name)),
            )
            session.add(repo)
        if body.external_remote_url is not None:
            url = body.external_remote_url.strip()
            if url and not url.startswith(("https://", "ssh://", "git@", "file://")):
                raise ValidationFailed("bad_remote_url", message="Use an https://, ssh://, git@ or file:// remote.")
            repo.external_remote_url = url or None
            repo.last_external_error = None
        if body.external_token is not None:
            repo.external_token_encrypted = encrypt(body.external_token) if body.external_token else None
    await session.commit()
    await session.refresh(skill)
    return SkillOut.model_validate(skill)


@router.get("/skills/{skill_id}/mirror")
async def mirror_status(skill_id: str, session: SessionDep, user: CurrentUser) -> dict:
    """External git mirror settings of a skill (the token is never returned)."""
    await get_skill_for(session, skill_id, user, ProjectRole.viewer)
    repo = await session.get(SkillRepo, skill_id)
    return {
        "external_remote_url": repo.external_remote_url if repo else None,
        "has_token": bool(repo and repo.external_token_encrypted),
        "last_external_push_at": repo.last_external_push_at.isoformat()
        if repo and repo.last_external_push_at
        else None,
        "last_external_error": repo.last_external_error if repo else None,
    }


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


# --- admin: curated lists ---------------------------------------------------------------


@router.get("/admin/hub/lists", response_model=list[CuratedListOut])
async def admin_lists(session: SessionDep, admin: AdminUser):
    return await _lists_out(session, await lists.all_lists(session))


@router.post("/admin/hub/lists", response_model=CuratedListOut, status_code=201)
async def create_list(body: CuratedListIn, session: SessionDep, admin: AdminUser):
    row = await lists.create_list(
        session,
        slug=body.slug,
        name=body.name,
        description=body.description,
        ordinal=body.ordinal,
        is_public=body.is_public,
        actor_id=admin.id,
    )
    await session.commit()
    await session.refresh(row)
    (out,) = await _lists_out(session, [row])
    return out


@router.put("/admin/hub/lists/{list_id}", response_model=CuratedListOut)
async def update_list(list_id: str, body: CuratedListIn, session: SessionDep, admin: AdminUser):
    row = await session.get(CuratedList, list_id)
    if row is None:
        raise NotFound("list_not_found")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    (out,) = await _lists_out(session, [row])
    return out


@router.delete("/admin/hub/lists/{list_id}", response_model=OkResponse)
async def delete_list(list_id: str, session: SessionDep, admin: AdminUser):
    row = await session.get(CuratedList, list_id)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return OkResponse()


@router.post("/admin/hub/lists/{list_id}/items/{skill_id}", response_model=CuratedListDetail)
async def add_list_item(list_id: str, skill_id: str, session: SessionDep, admin: AdminUser, note: str | None = None):
    row = await session.get(CuratedList, list_id)
    if row is None:
        raise NotFound("list_not_found")
    await lists.add_item(session, row, skill_id, note)
    await session.commit()
    (out,) = await _lists_out(session, [row])
    return CuratedListDetail(list=out, items=await _to_hub(session, await lists.skills_of(session, row, admin), admin))


@router.delete("/admin/hub/lists/{list_id}/items/{skill_id}", response_model=CuratedListDetail)
async def remove_list_item(list_id: str, skill_id: str, session: SessionDep, admin: AdminUser):
    row = await session.get(CuratedList, list_id)
    if row is None:
        raise NotFound("list_not_found")
    await lists.remove_item(session, row, skill_id)
    await session.commit()
    (out,) = await _lists_out(session, [row])
    return CuratedListDetail(list=out, items=await _to_hub(session, await lists.skills_of(session, row, admin), admin))
