from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from autoskill.models.project import ProjectRole
from autoskill.schemas.common import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    settings: dict = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    settings: dict | None = None


class ProjectOut(ORMModel):
    id: str
    name: str
    slug: str
    description: str | None
    settings: dict
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    my_role: ProjectRole | None = None
    member_count: int = 0


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    role: ProjectRole
    created_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: ProjectRole = ProjectRole.editor


class MemberUpdate(BaseModel):
    role: ProjectRole
