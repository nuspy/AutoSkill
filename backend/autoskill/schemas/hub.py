from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel
from autoskill.schemas.skill import SkillOut


class CategoryIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    name: dict[str, str]
    description: str | None = None
    ordinal: int = 0


class CategoryOut(ORMModel):
    id: str
    slug: str
    name: dict
    description: str | None
    ordinal: int
    count: int = 0


class HubSkill(SkillOut):
    rating_avg: float | None = None
    rating_count: int = 0
    published_version: str | None = None
    published_version_id: str | None = None
    category_slug: str | None = None
    is_favorite: bool = False
    project_slug: str = ""
    is_featured: bool = False
    published_at: datetime | None = None


class CuratedListOut(ORMModel):
    id: str
    slug: str
    name: dict
    description: str | None
    ordinal: int
    is_public: bool
    count: int = 0


class CuratedListIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    name: dict[str, str]
    description: str | None = None
    ordinal: int = 0
    is_public: bool = True


class CuratedListDetail(BaseModel):
    list: CuratedListOut
    items: list[HubSkill]


class HubHome(BaseModel):
    featured: list[HubSkill]
    latest: list[HubSkill]
    most_installed: list[HubSkill]
    top_rated: list[HubSkill] = Field(default_factory=list)
    categories: list[CategoryOut]
    lists: list[CuratedListOut] = Field(default_factory=list)
    public: bool


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class RatingOut(ORMModel):
    id: str
    user_id: str
    skill_id: str
    skill_version_id: str | None
    stars: int
    comment: str | None
    created_at: datetime
    updated_at: datetime
    user_name: str = ""


class ContributionIn(BaseModel):
    version_id: str | None = None
    message: str | None = Field(default=None, max_length=4000)


class ContributionDecision(BaseModel):
    accept: bool
    comment: str | None = Field(default=None, max_length=4000)


class ContributionOut(ORMModel):
    id: str
    source_skill_id: str
    source_version_id: str
    target_skill_id: str
    target_version_id: str | None
    proposed_by: str
    message: str | None
    state: str
    decided_by: str | None
    decided_at: datetime | None
    decision_comment: str | None
    created_at: datetime
    source_title: str = ""
    source_version: str = ""
    target_title: str = ""
    proposed_by_name: str = ""


class HubSearch(BaseModel):
    items: list[HubSkill]
    total: int


class HubSkillDetail(BaseModel):
    skill: HubSkill
    readme: str
    versions: list[dict]
    install_targets: list[dict]
    dependencies: list[dict]
    memory_public: list[dict]
    git_url: str | None
    zip_url: str | None
    my_installation: dict | None
    my_rating: RatingOut | None = None
    ratings: list[RatingOut] = Field(default_factory=list)


class InstallationOut(ORMModel):
    id: str
    device_id: str | None
    skill_id: str
    skill_version_id: str
    target_agent: str
    channel: str
    kind: str
    state: str
    installed_at: datetime | None
    confirmed_at: datetime | None
    last_run_at: datetime | None
    run_count: int
    created_at: datetime
    updated_at: datetime
    skill_title: str = ""
    skill_name: str = ""
    installed_version: str = ""
    latest_version: str | None = None
    latest_version_id: str | None = None
    update_available: bool = False


class InstallationIn(BaseModel):
    skill_version_id: str
    target_agent: str
    channel: str = "cli"
    kind: str = "permanent"
    device_id: str | None = None
    state: str = "installed"


class ForkIn(BaseModel):
    target_project_id: str
    title: str | None = Field(default=None, max_length=200)


class SkillPublishSettings(BaseModel):
    visibility: str | None = None
    category_id: str | None = None
    tags: list[str] | None = None
    external_remote_url: str | None = None  # "" clears the mirror
    external_token: str | None = None  # write-only; "" clears it
