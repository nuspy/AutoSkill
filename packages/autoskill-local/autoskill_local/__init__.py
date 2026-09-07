"""AutoSkill user-side CLI and companion MCP server."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

# One source of truth, and it is the package metadata rather than a literal kept here by hand.
# The two had already drifted — `pyproject.toml` said 0.2.2 while this file still said 0.2.1 — and
# that divergence is not cosmetic: the CLI reports `__version__` as `cli_version`, and the server
# compares it against the wheel it publishes to decide whether an agent needs updating. An agent that
# installs the new version and goes on announcing the old one is told to update again, and again.
try:
    __version__ = _installed_version("autoskill-local")
except PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0+dev"
