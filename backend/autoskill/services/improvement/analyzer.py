"""Deterministic analysis of what went wrong with a skill version: clusters of failures, issues and corrections."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.db.base import utcnow
from autoskill.models.skill_version import StepDefinition
from autoskill.models.trial import Run, RunAnnotation, RunStep, TrialSession

WINDOW_DAYS = 30
FAILURE_THRESHOLD = 3


def error_signature(error) -> str:
    if not error:
        return "unknown"
    text = error.get("message") if isinstance(error, dict) else str(error)
    text = str(text or "unknown").lower()
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<id>", text)
    text = re.sub(r"\d+", "<n>", text)
    text = re.sub(r"['\"].*?['\"]", "<str>", text)
    return text[:80].strip() or "unknown"


async def collect(session: AsyncSession, skill_id: str, version_id: str, *, window_days: int = WINDOW_DAYS) -> dict:
    since = utcnow() - timedelta(days=window_days)
    runs = (
        (
            await session.execute(
                select(Run)
                .where(Run.skill_id == skill_id, Run.skill_version_id == version_id, Run.started_at >= since)
                .order_by(Run.started_at.desc())
            )
        )
        .scalars()
        .all()
    )
    run_ids = [r.id for r in runs]
    # needs_review runs created by issue reports are counted through their issues, not as failures
    failed_runs = [r for r in runs if r.status in ("failed", "aborted") or r.human_feedback == "wrong"]
    steps = (
        (await session.execute(select(RunStep).where(RunStep.run_id.in_(run_ids)))).scalars().all() if run_ids else []
    )
    issues = (
        (
            await session.execute(
                select(RunAnnotation).where(
                    RunAnnotation.skill_id == skill_id, RunAnnotation.kind == "issue", RunAnnotation.created_at >= since
                )
            )
        )
        .scalars()
        .all()
    )
    trials = (
        (await session.execute(select(TrialSession).where(TrialSession.skill_version_id == version_id))).scalars().all()
    )
    definitions = {
        s.key: s
        for s in (
            await session.execute(select(StepDefinition).where(StepDefinition.skill_version_id == version_id))
        ).scalars()
    }

    clusters: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "run_ids": set(), "examples": []})
    for s in steps:
        if s.status in ("failed", "corrected", "stopped"):
            key = (s.step_key, error_signature(s.error) if s.status == "failed" else s.status)
            c = clusters[key]
            c["count"] += 1
            c["run_ids"].add(s.run_id)
            if len(c["examples"]) < 3:
                c["examples"].append({"run_id": s.run_id, "error": s.error, "outputs": s.outputs})
    for a in issues:
        key = (a.step_key or "*", "issue:" + error_signature({"message": a.text}))
        c = clusters[key]
        c["count"] += 1
        if a.run_id:
            c["run_ids"].add(a.run_id)
        if len(c["examples"]) < 3:
            c["examples"].append({"issue_id": a.id, "text": a.text, "severity": a.severity})
    corrections = [c for t in trials for c in t.corrections]
    for c in corrections:
        key = (c["step_key"], "correction")
        clusters[key]["count"] += 1
        if len(clusters[key]["examples"]) < 3:
            clusters[key]["examples"].append({"text": c["text"]})

    ranked = sorted(
        (
            {
                "step_key": k[0],
                "signature": k[1],
                "count": v["count"],
                "run_ids": sorted(v["run_ids"]),
                "examples": v["examples"],
                "step_title": definitions[k[0]].title if k[0] in definitions else None,
                "step_kind": definitions[k[0]].kind if k[0] in definitions else None,
            }
            for k, v in clusters.items()
        ),
        key=lambda c: -c["count"],
    )
    total = len(runs)
    return {
        "window_days": window_days,
        "runs_total": total,
        "runs_failed": len(failed_runs),
        "failure_rate": round(len(failed_runs) / total, 3) if total else None,
        "golden_runs": [r.id for r in runs if r.is_golden],
        "issues": len(issues),
        "corrections": len(corrections),
        "clusters": ranked[:12],
        "source_run_ids": [r.id for r in failed_runs][:50],
        "source_issue_ids": [a.id for a in issues][:50],
    }


def should_trigger(analysis: dict) -> str | None:
    if analysis["runs_failed"] >= FAILURE_THRESHOLD:
        return "auto_failure_threshold"
    if analysis["issues"] >= 2:
        return "issue_reports"
    return None
