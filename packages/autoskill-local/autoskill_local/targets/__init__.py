"""Local target adapters: where skills go and how MCP servers are registered on this machine."""

from __future__ import annotations

from autoskill_local.targets.base import LocalTarget
from autoskill_local.targets.builtin import TARGETS

_home_overrides: dict[str, str] = {}


def set_home_overrides(overrides: dict[str, str] | None) -> None:
    """Record where the person says each agent lives, from their own AutoSkill config.

    Discovery handles the layouts we know about; this handles the ones we do not, because an agent
    can be installed anywhere and guessing wrong is silent — the skill lands in a directory nothing
    reads and every step still reports success.

    It is set once, from the CLI's configuration, rather than threaded through a dozen call sites
    where it would be forgotten at precisely the one that mattered.
    """
    _home_overrides.clear()
    _home_overrides.update({k: str(v) for k, v in (overrides or {}).items() if v})


def get_target(target_id: str, home=None, home_dir=None) -> LocalTarget:
    try:
        cls = TARGETS[target_id]
    except KeyError as exc:
        raise KeyError(f"unknown target {target_id!r}; known: {sorted(TARGETS)}") from exc
    # An explicit `home` outranks everything, the person's configuration outranks discovery.
    if home is None:
        home_dir = home_dir or _home_overrides.get(target_id)
    return cls(home=home, home_dir=home_dir)


def detect_targets(home=None) -> list[str]:
    return [tid for tid in TARGETS if get_target(tid, home=home).detect()]
