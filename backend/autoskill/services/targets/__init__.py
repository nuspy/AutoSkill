"""Target agent adapters (install paths, MCP registration snippets, INSTALL.md rendering)."""

from __future__ import annotations

from autoskill.services.targets.base import TargetAdapter
from autoskill.services.targets.builtin import ADAPTERS


def get_adapter(target: str) -> TargetAdapter:
    try:
        return ADAPTERS[target]
    except KeyError as exc:
        raise KeyError(f"unknown target agent {target!r}; known: {sorted(ADAPTERS)}") from exc


def list_targets() -> list[dict]:
    return [a.describe() for a in ADAPTERS.values()]
