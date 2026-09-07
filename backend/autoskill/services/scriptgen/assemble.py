"""Turn an McpSpec into a package with a command line instead of an MCP server.

The tool modules are byte-for-byte the ones `mcpgen` writes: `run(**kwargs) -> dict` inside
`<pkg>/tools/<name>.py`, already checked by the static analysis. Only the wrapper differs — an
argparse front end rather than a server — because that was the whole argument for scripts: the
logic is the same, and what changes is how the agent reaches it.

What the generated CLI gives that a bare script would not:

* `--help` per command, with the parameters and their descriptions: the contract, readable by a
  person and by a model, kept next to the code instead of copied into a prompt.
* `--list-tools`, the same JSON the MCP server prints, so `autoskill mcp check` works either way.
* JSON on stdout and a non-zero exit code on failure, so the caller does not have to parse prose.
* telemetry through the companion, which an MCP tool cannot do when nobody is watching: a step run
  from cron at three in the morning shows up among the runs like any other.
"""

from __future__ import annotations

import json

from autoskill.services.mcpgen.assemble import (
    JSON_TYPES,
    input_schema,
    package_name,
    render_readme,
    render_tests,
    render_tool_module,
)
from autoskill.services.mcpgen.spec import McpSpec, McpTool


def render_pyproject(server_name: str, spec: McpSpec, version: str) -> str:
    """Same package, minus the `mcp` dependency: nothing here speaks the protocol."""
    pkg = package_name(server_name)
    deps = sorted(set(spec.dependencies))
    dep_lines = ",\n".join(f'    "{d}"' for d in deps)
    return f'''[project]
name = "{server_name}"
version = "{version}"
description = {json.dumps(spec.description[:200])}
requires-python = ">=3.11"
dependencies = [
{dep_lines}
]

[project.scripts]
{server_name} = "{pkg}.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{pkg}"]
'''


TELEMETRY = '''"""Report to AutoSkill when this machine is connected, stay quiet when it is not.

The companion (`autoskill login`) holds the address and the key. Without it the commands still
work: telemetry is an addition, never a condition for running.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager


def _companion():
    try:
        from autoskill_local import companion
    except ImportError:
        return None
    # stderr carries the error of the step as JSON: the HTTP chatter of the reporting client
    # would make it unparsable for whoever called the command
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return companion


@contextmanager
def report(skill_name: str, step_key: str, tool_name: str, inputs: dict):
    """Wrap one command: opens a run when there is none, records the step, closes what it opened."""
    comp = _companion()
    run_id = os.environ.get("AUTOSKILL_RUN_ID") or None
    opened = False
    if comp is not None and run_id is None:
        try:
            started = comp.start_run(skill_name=skill_name, inputs_summary=step_key)
            run_id = (started or {}).get("run_id")
            opened = bool(run_id)
        except Exception:  # noqa: BLE001 - telemetry must never break the command
            run_id = None
    started_at = time.time()
    outcome = {"status": "succeeded", "outputs": None, "error": None}
    try:
        yield outcome
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for the caller
        outcome["status"], outcome["error"] = "failed", str(exc)
        raise
    finally:
        if comp is not None and run_id:
            try:
                comp.log_step(
                    run_id=run_id,
                    step_key=step_key,
                    status=outcome["status"],
                    inputs=inputs,
                    outputs=outcome["outputs"],
                    error=outcome["error"],
                    duration_ms=int((time.time() - started_at) * 1000),
                    tool_name=tool_name,
                )
                if opened:
                    comp.end_run(run_id, status=outcome["status"], error=outcome["error"])
            except Exception:  # noqa: BLE001
                pass
'''


def _arguments(tool: McpTool) -> str:
    """argparse declarations from the same schema the MCP tool publishes."""
    lines = []
    for p in tool.params:
        typ = JSON_TYPES[p.type]
        flag = f"--{p.name.replace('_', '-')}"
        if p.type == "boolean":
            lines.append(
                f"    p.add_argument({json.dumps(flag)}, dest={json.dumps(p.name)}, "
                f"action='store_true', help={json.dumps(p.description)})"
            )
            continue
        required = "True" if p.required else "False"
        default = json.dumps(p.default) if p.default is not None else "None"
        cast = "json.loads" if p.type in ("array", "object") else typ
        lines.append(
            f"    p.add_argument({json.dumps(flag)}, dest={json.dumps(p.name)}, type={cast}, "
            f"required={required}, default={default}, help={json.dumps(p.description)})"
        )
    if tool.side_effects != "read_only":
        lines.append(
            "    p.add_argument('--apply', dest='dry_run', action='store_false', default=True,\n"
            "                   help='Actually apply the effect. Without it the command only describes what it would do.')"
        )
    if tool.side_effects == "irreversible":
        lines.append(
            "    p.add_argument('--confirmation-token', dest='confirmation_token', default=None,\n"
            "                   help='Token minted by AutoSkill when the person authorized real execution.')"
        )
    return "\n".join(lines) or "    pass"


def render_cli(server_name: str, spec: McpSpec, tools: list[McpTool], skill_name: str) -> str:
    pkg = package_name(server_name)
    subcommands = []
    dispatch = []
    for tool in tools:
        effects = "" if tool.side_effects == "read_only" else f" [{tool.side_effects}]"
        subcommands.append(
            f"\n\ndef _add_{tool.name}(sub) -> None:\n"
            f"    p = sub.add_parser({json.dumps(tool.name)}, help={json.dumps(tool.description[:200] + effects)},\n"
            f"                       description={json.dumps(tool.description)})\n"
            f"{_arguments(tool)}\n"
            f"    p.set_defaults(_step_key={json.dumps(tool.step_key)}, _tool={json.dumps(tool.name)})"
        )
        dispatch.append(f"    _add_{tool.name}(sub)")
    # repr, not json.dumps: this is Python source, where the literals are True/False/None
    tools_json = repr([{"name": t.name, "step_key": t.step_key, "side_effects": t.side_effects} for t in tools])
    schemas = repr({t.name: input_schema(t) for t in tools})
    header = (
        f'"""{server_name}: command line generated by AutoSkill.\n\n{spec.description}\n\n'
        f"Every step is a subcommand: `{server_name} <step> --help` prints its parameters.\n"
        f"Results are printed as JSON on stdout; the exit code is non-zero when the step fails.\n"
        f"Steps with effects only describe them unless `--apply` is given.\n"
        f'"""\n'
    )
    body = f'''
from __future__ import annotations

import argparse
import importlib
import json
import sys

from {pkg} import telemetry

SKILL_NAME = {json.dumps(skill_name)}
TOOLS = {tools_json}
SCHEMAS = {schemas}
{"".join(subcommands)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog={json.dumps(server_name)}, description={json.dumps(spec.description[:300])})
    parser.add_argument("--list-tools", action="store_true", help="Print the steps as JSON and exit.")
    parser.add_argument("--schemas", action="store_true", help="Print the parameter schemas as JSON and exit.")
    sub = parser.add_subparsers(dest="step")
{chr(10).join(dispatch)}
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_tools:
        print(json.dumps(TOOLS, indent=2))
        return 0
    if args.schemas:
        print(json.dumps(SCHEMAS, indent=2))
        return 0
    if not args.step:
        parser.print_help()
        return 2
    params = {{k: v for k, v in vars(args).items() if not k.startswith("_") and k not in ("step", "list_tools", "schemas")}}
    module = importlib.import_module(f"{pkg}.tools.{{args._tool}}")
    if hasattr(module, "_require_confirmation"):
        module._require_confirmation(params)
    try:
        with telemetry.report(SKILL_NAME, args._step_key, args._tool, params) as outcome:
            result = module.run(**params)
            outcome["outputs"] = result if isinstance(result, dict) else {{"result": result}}
    except Exception as exc:  # noqa: BLE001 - reported as JSON, like any other outcome
        print(json.dumps({{"error": str(exc), "step": args._step_key}}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return header + body


def render_usage(server_name: str, tools: list[McpTool]) -> str:
    """The lines to paste into SKILL.md: how the agent calls each step."""
    lines = [
        "## Steps of this skill",
        "",
        f"Each step is a command. Run `{server_name} <step> --help` to see its parameters,",
        f"or `{server_name} --schemas` for every parameter schema as JSON.",
        "Results are printed as JSON on stdout; a non-zero exit code means the step failed.",
        "",
    ]
    for tool in tools:
        flags = " ".join(f"--{p.name.replace('_', '-')} <{p.type}>" for p in tool.params if p.required)
        suffix = ""
        if tool.side_effects != "read_only":
            suffix = "  # add --apply to perform it for real"
        lines.append(f"- **{tool.step_key}** — {tool.description}")
        lines.append(f"  ```bash")
        lines.append(f"  {server_name} {tool.name}{' ' + flags if flags else ''}{suffix}")
        lines.append("  ```")
        if tool.side_effects == "irreversible":
            lines.append("  Irreversible: needs `--confirmation-token` authorized in AutoSkill.")
    return "\n".join(lines) + "\n"


def assemble_scripts(server_name: str, version: str, spec: McpSpec, skill_name: str) -> dict[str, bytes]:
    pkg = package_name(server_name)
    files: dict[str, bytes] = {
        "pyproject.toml": render_pyproject(server_name, spec, version).encode(),
        "README.md": render_readme(server_name, spec, spec.tools).encode(),
        "USAGE.md": render_usage(server_name, spec.tools).encode(),
        ".env.example": ("\n".join(f"{e.name}=" for e in spec.env_requirements) + "\n").encode(),
        f"{pkg}/__init__.py": f'"""{server_name} generated by AutoSkill."""\n'.encode(),
        f"{pkg}/cli.py": render_cli(server_name, spec, spec.tools, skill_name).encode(),
        f"{pkg}/telemetry.py": TELEMETRY.encode(),
        f"{pkg}/tools/__init__.py": b"",
        "tests/test_tools.py": render_tests(server_name, spec.tools).encode(),
    }
    for tool in spec.tools:
        # identical to the MCP package: same logic, different wrapper
        files[f"{pkg}/tools/{tool.name}.py"] = render_tool_module(tool).encode()
    return files
