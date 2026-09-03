"""Review queue for reviewers/admins and submission endpoints for authors."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import CurrentUser, ReviewerUser, SessionDep
from autoskill.api.v1.skills import get_skill_for
from autoskill.core.errors import NotFound
from autoskill.models.project import ProjectRole
from autoskill.models.review import ReviewDecision, ReviewRequest
from autoskill.models.skill import Skill
from autoskill.models.skill_version import SkillVersion
from autoskill.models.user import User
from autoskill.schemas.common import OkResponse
from autoskill.schemas.review import (
    DecisionIn,
    ReviewBundle,
    ReviewDecisionOut,
    ReviewQueueItem,
    ReviewRequestOut,
    SubmitReview,
)
from autoskill.services.memory.store import list_entries
from autoskill.services.packaging.store import load_package
from autoskill.services.review import service
from autoskill.services.versioning.changes import compare

router = APIRouter(tags=["review"])


@router.post("/versions/{version_id}/submit-review", response_model=ReviewRequestOut, status_code=201)
async def submit(version_id: str, body: SubmitReview, session: SessionDep, user: CurrentUser):
    version = await session.get(SkillVersion, version_id)
    if version is None:
        raise NotFound("version_not_found")
    await get_skill_for(session, version.skill_id, user, ProjectRole.editor)
    req = await service.submit(session, version, user, body.summary)
    await session.commit()
    await session.refresh(req)
    return req


@router.post("/review/{request_id}/withdraw", response_model=ReviewRequestOut)
async def withdraw(request_id: str, session: SessionDep, user: CurrentUser):
    req = await _req(session, request_id)
    await get_skill_for(session, req.skill_id, user, ProjectRole.editor)
    await service.withdraw(session, req, user)
    await session.commit()
    await session.refresh(req)
    return req


async def _req(session, request_id: str) -> ReviewRequest:
    req = await session.get(ReviewRequest, request_id)
    if req is None:
        raise NotFound("review_request_not_found")
    return req


async def _item(session, req: ReviewRequest) -> ReviewQueueItem:
    skill = await session.get(Skill, req.skill_id)
    version = await session.get(SkillVersion, req.skill_version_id)
    author = await session.get(User, req.requested_by)
    item = ReviewQueueItem.model_validate(req)
    item.skill_title = skill.title if skill else ""
    item.skill_name = skill.name if skill else ""
    item.version = version.version if version else ""
    item.requested_by_name = author.display_name if author else ""
    return item


@router.get("/review/queue", response_model=list[ReviewQueueItem])
async def queue(session: SessionDep, user: ReviewerUser, state: str | None = None, mine: bool = False):
    rows = await service.queue(session, state=state, assignee_id=user.id if mine else None)
    return [await _item(session, r) for r in rows]


@router.get("/review/mine", response_model=list[ReviewQueueItem])
async def my_requests(session: SessionDep, user: CurrentUser):
    res = await session.execute(
        select(ReviewRequest).where(ReviewRequest.requested_by == user.id).order_by(ReviewRequest.created_at.desc())
    )
    return [await _item(session, r) for r in res.scalars()]


@router.get("/review/{request_id}", response_model=ReviewBundle)
async def bundle(request_id: str, session: SessionDep, user: CurrentUser):
    req = await _req(session, request_id)
    if user.role.value not in ("admin", "reviewer"):
        await get_skill_for(session, req.skill_id, user, ProjectRole.viewer)
    skill = await session.get(Skill, req.skill_id)
    version = await session.get(SkillVersion, req.skill_version_id)
    previous = (
        await session.get(SkillVersion, skill.current_published_version_id)
        if skill.current_published_version_id
        else None
    )
    if previous is not None and previous.id == version.id:
        previous = None
    diff = await compare(session, skill, version, previous)
    pkg = load_package(skill.name, version)
    files = [{"path": p, "size": len(b)} for p, b in sorted(pkg.files.items())]
    decisions = (
        (
            await session.execute(
                select(ReviewDecision)
                .where(ReviewDecision.review_request_id == req.id)
                .order_by(ReviewDecision.created_at)
            )
        )
        .scalars()
        .all()
    )
    memory = await list_entries(session, skill.id, status="active")
    return ReviewBundle(
        request=ReviewRequestOut.model_validate(req),
        skill_title=skill.title,
        skill_name=skill.name,
        version=version.version,
        version_id=version.id,
        previous_version=previous.version if previous else None,
        diff=diff,
        files=files,
        decisions=[ReviewDecisionOut.model_validate(d) for d in decisions],
        memory_count=len(memory),
    )


@router.post("/review/{request_id}/assign", response_model=ReviewRequestOut)
async def assign(request_id: str, session: SessionDep, user: ReviewerUser):
    req = await _req(session, request_id)
    await service.assign(session, req, user)
    await session.commit()
    await session.refresh(req)
    return req


@router.post("/review/{request_id}/decision", response_model=ReviewDecisionOut)
async def decision(request_id: str, body: DecisionIn, session: SessionDep, user: ReviewerUser):
    req = await _req(session, request_id)
    row = await service.decide(
        session, req, user, decision=body.decision, comment=body.comment, file_comments=body.file_comments
    )
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/review/count", response_model=dict)
async def count(session: SessionDep, user: ReviewerUser):
    return {"open": await service.open_count(session)}


@router.get("/review/health", response_model=OkResponse)
async def health():
    return OkResponse()
