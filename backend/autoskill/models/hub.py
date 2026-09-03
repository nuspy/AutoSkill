from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from autoskill.db.base import Base, IdMixin, TimestampMixin, TZDateTime


class Category(IdMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {"en": "...", "it": "..."}
    description: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Installation(IdMixin, TimestampMixin, Base):
    """A skill installed by a user on one of their devices (trial or permanent)."""

    __tablename__ = "installations"
    __table_args__ = (UniqueConstraint("user_id", "device_key", "skill_id", "target_agent", name="uq_installation"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(36))
    device_key: Mapped[str] = mapped_column(String(36), default="-", nullable=False)  # device_id or "-"
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_agent: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(16), default="zip", nullable=False
    )  # cli | zip | git | install_md | manual
    kind: Mapped[str] = mapped_column(String(16), default="permanent", nullable=False)  # trial | permanent
    state: Mapped[str] = mapped_column(
        String(16), default="downloaded", nullable=False
    )  # downloaded | installed | confirmed | updated | removed
    installed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Favorite(IdMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_favorite"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class SkillRepo(Base):
    __tablename__ = "skill_repos"

    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    head_version_id: Mapped[str | None] = mapped_column(String(36))
    last_pushed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    public_clone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DownloadGrant(IdMixin, TimestampMixin, Base):
    """Capability token that lets anyone holding the URL download one install bundle (no login).

    The token is stored hashed (lookup) and encrypted (so the UI can show the URL again); a grant
    never gives write access. Trial grants live as long as the trial is open or kept installed;
    version grants expire at `expires_at` or when revoked.
    """

    __tablename__ = "download_grants"

    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # trial | version
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    trial_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    target_agent: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(36))
    label: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
