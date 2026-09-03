from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from autoskill.schemas.user import UserOut


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    locale: str = Field(default="en", max_length=8)
    invite_token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class DeviceStartRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=120)
    device_os: str | None = Field(default=None, max_length=80)
    agent_targets: list[str] = Field(default_factory=list)


class DeviceStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int = 5


class DeviceTokenRequest(BaseModel):
    device_code: str


class DeviceTokenResponse(BaseModel):
    status: str  # pending | approved | denied | expired
    api_key: str | None = None
    device_id: str | None = None
    server_url: str | None = None


class DeviceConfirmRequest(BaseModel):
    user_code: str
    approve: bool = True


class DevicePendingOut(BaseModel):
    user_code: str
    device_name: str
    device_os: str | None
    agent_targets: list[str]
    expires_at: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class InvitationIn(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(admin|reviewer|member)$")
    project_id: str | None = None
    expires_in_days: int = Field(default=7, ge=1, le=90)


class InvitationOut(BaseModel):
    id: str
    email: str
    role: str | None
    project_id: str | None
    invited_by: str | None
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime
    invite_url: str | None = None  # only right after creation
