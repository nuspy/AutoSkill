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
    # optional mirror: every publish is pushed to this remote (token stored encrypted, never returned)
    external_remote_url: Mapped[str | None] = mapped_column(String(500))
    external_token_encrypted: Mapped[str | None] = mapped_column(Text)
    last_external_push_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_external_error: Mapped[str | None] = mapped_column(Text)


class Rating(IdMixin, TimestampMixin, Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_rating"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_version_id: Mapped[str | None] = mapped_column(String(36))
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class Contribution(IdMixin, TimestampMixin, Base):
    """A variant proposes its changes back to the skill it was forked from."""

    __tablename__ = "contributions"

    source_skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_version_id: Mapped[str | None] = mapped_column(String(36))  # draft created on acceptance
    proposed_by: Mapped[str] = mapped_column(String(36), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="open", nullable=False)  # open | accepted | rejected
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    decision_comment: Mapped[str | None] = mapped_column(Text)


class CuratedList(IdMixin, TimestampMixin, Base):
    __tablename__ = "curated_lists"

    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {"en": ..., "it": ...}
    description: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))


class CuratedListItem(IdMixin, Base):
    __tablename__ = "curated_list_items"
    __table_args__ = (UniqueConstraint("list_id", "skill_id", name="uq_list_item"),)

    list_id: Mapped[str] = mapped_column(ForeignKey("curated_lists.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


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
