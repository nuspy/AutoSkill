from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from autoskill.models.user import UserRole
from autoskill.schemas.common import ORMModel


class UserOut(ORMModel):
    id: str
    email: str
    display_name: str
    locale: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    locale: str | None = Field(default=None, max_length=8)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
