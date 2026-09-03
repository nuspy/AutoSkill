"""Job registry. Import every module that declares @job functions."""

from __future__ import annotations


def register_all_jobs() -> None:
    from autoskill.jobs import drafting, improvement, interview, mcp, memory, system  # noqa: F401
    from autoskill.services.procedures import defs  # noqa: F401  (registers procedure definitions)
