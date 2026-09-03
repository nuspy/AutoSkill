from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from autoskill.schemas.common import ORMModel


class NotificationOut(ORMModel):
    id: str
    kind: str
    title: str
    body: str | None
    subject_type: str | None
    subject_id: str | None
    payload: dict
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


class PreferenceUpdate(BaseModel):
    kind: str
    in_app: bool = True
    email: bool = False
