"""Job registry. Import every module that declares @job functions."""

from __future__ import annotations


def register_all_jobs() -> None:
    from autoskill.jobs import system  # noqa: F401
