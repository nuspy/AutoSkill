"""System settings with defaults, stored in the database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.models.system_setting import SystemSetting

DEFAULTS: dict[str, Any] = {
    "registration_open": True,
    "public_hub": False,
    "review_required_for_private": True,
    "allow_self_review": False,
    "daily_token_cap_per_project": 2_000_000,
    "telemetry_retention_days": 180,
    "trial_max_iterations_per_step": 5,
    "checkpoint_timeout_minutes": 120,
    "auto_confirm_after_confirmations": 3,
    "download_rate_per_minute": 120,
    "max_active_download_links_per_user": 50,
    # Output ceiling for the automatic tasks (interview, drafting, review, memory...). Off by
    # default: the model writes as much as it needs, up to whatever its own limit is. Turn it on
    # to cap the spend — but keep it generous, because a reasoning model can burn the whole budget
    # thinking and return nothing at all.
    "llm_output_limit_enabled": False,
    "llm_output_limit_tokens": 12000,
}


async def get_setting(session: AsyncSession, key: str) -> Any:
    row = await session.get(SystemSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.value


async def get_all_settings(session: AsyncSession) -> dict[str, Any]:
    res = await session.execute(select(SystemSetting))
    stored = {row.key: row.value for row in res.scalars()}
    return {**DEFAULTS, **stored}


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    row = await session.get(SystemSetting, key)
    if row is None:
        session.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
