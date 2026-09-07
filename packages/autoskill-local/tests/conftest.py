"""Nothing in this suite may reach a real agent installation.

This is not a precaution written in the abstract. A test that patched `Path.home()` to a temporary
directory was still resolving Hermes through `$HERMES_HOME`, which points at the live installation on
the developer's own machine: the suite installed a fixture skill into it, left a stray backup folder
beside the real skills, and rewrote the agent's `config.yaml` to add five MCP servers that nothing
had asked for. Every test passed while it happened.

Patching the home directory is therefore not enough on its own, because discovery deliberately looks
past it — an agent can be installed anywhere, and the environment variable is how it says so. So the
variables are removed for the whole session: inside the suite there is no agent anywhere but the
temporary home a fixture creates.
"""

from __future__ import annotations

import pytest

from autoskill_local import targets as targets_mod
from autoskill_local.targets import TARGETS


@pytest.fixture(autouse=True)
def no_real_agents(monkeypatch):
    for cls in TARGETS.values():
        if cls.home_env:
            monkeypatch.delenv(cls.home_env, raising=False)
    # A previous test's configuration must not leak into the next one either.
    targets_mod.set_home_overrides(None)
