"""Hub jobs: mirror a published version to the skill's external git remote."""

from __future__ import annotations

import asyncio

from autoskill.core.crypto import decrypt
from autoskill.core.jobs import JobContext, job
from autoskill.db.base import utcnow
from autoskill.db.session import get_session_factory
from autoskill.models.hub import SkillRepo
from autoskill.models.skill_version import SkillVersion
from autoskill.services.distribution import git_repo


@job("distribution.push_external")
async def push_external(ctx: JobContext, skill_id: str, version_id: str, **_) -> dict:
    async with get_session_factory()() as session:
        repo = await session.get(SkillRepo, skill_id)
        version = await session.get(SkillVersion, version_id)
        if repo is None or version is None or not repo.external_remote_url:
            return {"pushed": False, "reason": "no_remote"}
        token = decrypt(repo.external_token_encrypted) if repo.external_token_encrypted else None
        try:
            sha = await asyncio.to_thread(
                git_repo.push_external,
                __import__("pathlib").Path(repo.path),
                repo.external_remote_url,
                token,
                version.version,
            )
            repo.last_external_push_at = utcnow()
            repo.last_external_error = None
            result = {"pushed": True, "sha": sha}
        except Exception as exc:  # noqa: BLE001 - recorded on the repo, visible in the UI
            repo.last_external_error = str(exc)[:2000]
            result = {"pushed": False, "error": str(exc)[:500]}
        await session.commit()
    return result
