"""autoskill-companion: MCP server (stdio) that installed skills call for checkpoints and telemetry.

Environment: AUTOSKILL_URL, AUTOSKILL_API_KEY (from `autoskill login` or a project key),
optional AUTOSKILL_SESSION_TOKEN (trial). Tools never raise on server errors: they return a dict
with "error" so the agent can continue and report the problem.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

try:  # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from autoskill_local.client import Client, ServerError
from autoskill_local.config import LocalConfig

mcp = _Server("autoskill-companion", instructions="Checkpoints and run telemetry for AutoSkill skills.")

_client: Client | None = None
_state: dict[str, Any] = {"trial_token": None, "skill_id": None, "run_id": None}


def set_client(client: Client | None) -> None:
    """Tests inject a client with a mocked transport."""
    global _client
    _client = client


def get_client() -> Client:
    global _client
    if _client is None:
        cfg = LocalConfig.load()
        url = os.environ.get("AUTOSKILL_URL") or cfg.server_url
        if not url:
            raise RuntimeError("AUTOSKILL_URL is not set and no `autoskill login` was done")
        _state["trial_token"] = os.environ.get("AUTOSKILL_SESSION_TOKEN")
        _client = Client(url, api_key=os.environ.get("AUTOSKILL_API_KEY") or cfg.api_key, trial_token=_state["trial_token"])
    return _client


def _call(fn):
    try:
        return fn()
    except ServerError as exc:
        return {"error": exc.code or "server_error", "message": str(exc), "status": exc.status}
    except Exception as exc:  # noqa: BLE001
        return {"error": "unreachable", "message": str(exc)}


@mcp.tool()
def start_run(skill_name: str, skill_version: str | None = None, agent_target: str | None = None, inputs_summary: str | None = None) -> dict:
    """Open a run before the first step. Returns run_id and the trial mode (interactive/async/production)."""

    def go():
        body = {"skill_name": skill_name, "skill_version": skill_version, "agent_target": agent_target, "inputs_summary": inputs_summary}
        res = get_client().post("/telemetry/runs", body)
        _state["run_id"] = res["run_id"]
        return res

    return _call(go)


@mcp.tool()
def checkpoint(run_id: str, step_key: str, phase: str, proposal: dict | None = None, iteration: int | None = None) -> dict:
    """Register a step phase (explain | preview | execute | verify) and get the decision, or 'pending'.

    In an interactive trial the person decides from the AutoSkill web UI: when the result is pending,
    call await_decision with the checkpoint_id until a decision arrives, then obey it.
    """

    def go():
        body = {"run_id": run_id, "step_key": step_key, "phase": phase, "proposal": proposal or {}, "iteration": iteration}
        return get_client().post("/checkpoints", body)

    return _call(go)


@mcp.tool()
def await_decision(checkpoint_id: str, timeout_s: int = 50) -> dict:
    """Wait (max 50 s per call) for the person's decision on a checkpoint. Repeat while status is 'pending'."""

    def go():
        return get_client().get(f"/checkpoints/{checkpoint_id}", params={"wait": max(0, min(int(timeout_s), 50))}, timeout=70)

    return _call(go)


@mcp.tool()
def log_step(run_id: str, step_key: str, status: str = "succeeded", title: str | None = None, inputs: dict | None = None, outputs: dict | None = None, error: str | None = None, duration_ms: int | None = None, tool_name: str | None = None) -> dict:
    """Record the outcome of a step (status: succeeded | failed | skipped | corrected)."""

    def go():
        body = {"step_key": step_key, "status": status, "title": title, "inputs": inputs, "outputs": outputs, "error": {"message": error} if error else None, "duration_ms": duration_ms, "tool_name": tool_name}
        key = f"{run_id}:{step_key}:{int(time.time() * 1000)}"
        return get_client().post_or_queue(f"/telemetry/runs/{run_id}/steps", body, headers={"Idempotency-Key": key})

    return _call(go)


@mcp.tool()
def end_run(run_id: str, status: str = "succeeded", summary: str | None = None, error: str | None = None) -> dict:
    """Close the run (status: succeeded | failed | aborted | needs_review)."""

    def go():
        return get_client().post_or_queue(f"/telemetry/runs/{run_id}/end", {"status": status, "summary": summary, "error": {"message": error} if error else None})

    return _call(go)


@mcp.tool()
def report_issue(description: str, severity: str = "medium", run_id: str | None = None, step_key: str | None = None, skill_name: str | None = None, evidence: dict | None = None) -> dict:
    """Report that a step could not be done as described (feeds the improvement loop)."""

    def go():
        return get_client().post_or_queue("/telemetry/issues", {"description": description, "severity": severity, "run_id": run_id, "step_key": step_key, "skill_name": skill_name, "evidence": evidence})

    return _call(go)


@mcp.tool()
def get_step_guidance(skill_id: str, step_key: str) -> dict:
    """Latest instruction, corrections and memory notes for a step (use after a 'change' decision)."""
    return _call(lambda: get_client().get(f"/telemetry/guidance/{skill_id}/{step_key}"))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["json", "main", "mcp"]
