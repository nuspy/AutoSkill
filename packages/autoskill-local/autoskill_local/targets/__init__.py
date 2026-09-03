"""Local target adapters: where skills go and how MCP servers are registered on this machine."""

from __future__ import annotations

from autoskill_local.targets.base import LocalTarget
from autoskill_local.targets.builtin import TARGETS


def get_target(target_id: str, home=None) -> LocalTarget:
    try:
        cls = TARGETS[target_id]
    except KeyError as exc:
        raise KeyError(f"unknown target {target_id!r}; known: {sorted(TARGETS)}") from exc
    return cls(home=home)


def detect_targets(home=None) -> list[str]:
    return [tid for tid, cls in TARGETS.items() if cls(home=home).detect()]
