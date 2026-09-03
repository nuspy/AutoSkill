from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autoskill.schemas.common import ORMModel


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    description: str | None = None
    access_notes: str | None = None
    schema_def: dict = Field(default_factory=dict)
    sensitivity: str = "internal"


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = None
    description: str | None = None
    access_notes: str | None = None
    schema_def: dict | None = None
    sensitivity: str | None = None


class DataSourceOut(ORMModel):
    id: str
    project_id: str
    name: str
    kind: str
    description: str | None
    access_notes: str | None
    schema_def: dict
    sample_refs: list[dict]
    sensitivity: str
    created_at: datetime
    updated_at: datetime
