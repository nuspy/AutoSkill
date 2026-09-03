"""Structured output of the MCP author and the static safety checks."""

from __future__ import annotations

import ast
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

ALLOWED_TOP_LEVEL_IMPORTS = {
    # stdlib
    "json",
    "csv",
    "re",
    "os",
    "pathlib",
    "datetime",
    "time",
    "math",
    "statistics",
    "decimal",
    "collections",
    "itertools",
    "functools",
    "typing",
    "dataclasses",
    "hashlib",
    "base64",
    "uuid",
    "textwrap",
    "string",
    "shutil",
    "tempfile",
    "glob",
    "fnmatch",
    "io",
    "zipfile",
    "tarfile",
    "email",
    "imaplib",
    "smtplib",
    "poplib",
    "mimetypes",
    "urllib",
    "html",
    "xml",
    "sqlite3",
    "logging",
    "enum",
    "copy",
    "operator",
    "difflib",
    "unicodedata",
    "zoneinfo",
    "calendar",
    "locale",
    "random",
    "secrets",
    "struct",
    "codecs",
    "contextlib",
    "abc",
    "numbers",
    "fractions",
    # allowed third party
    "pandas",
    "openpyxl",
    "httpx",
    "yaml",
    "dateutil",
    "pydantic",
    "requests",
    "xlrd",
    "docx",
    "pypdf",
    "sqlalchemy",
    "psycopg",
    "pymysql",
    "ldap3",
    "icalendar",
}
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "input",
}
FORBIDDEN_MODULES = {
    "subprocess",
    "ctypes",
    "socket",
    "multiprocessing",
    "signal",
    "pty",
    "importlib",
    "pickle",
    "marshal",
    "shelve",
    "code",
    "codeop",
}
NETWORK_MODULES = {
    "httpx",
    "requests",
    "urllib",
    "imaplib",
    "smtplib",
    "poplib",
    "ldap3",
    "psycopg",
    "pymysql",
    "sqlalchemy",
}
SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][A-Za-z0-9_\-]{12,}['\"]")

SideEffects = Literal["read_only", "reversible", "irreversible"]


class ToolParam(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    type: Literal["string", "integer", "number", "boolean", "array", "object"] = "string"
    description: str = ""
    required: bool = True
    default: Any = None


class McpTool(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=60)
    step_key: str
    description: str = Field(min_length=1, max_length=600)
    side_effects: SideEffects = "read_only"
    network: bool = False
    params: list[ToolParam] = Field(default_factory=list)
    returns: str = "dict with the results"
    code: str = Field(
        min_length=1, description="Body of `def run(**kwargs) -> dict` at module level; may define helpers."
    )


class McpEnvRequirement(BaseModel):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=60)
    description: str = ""
    secret: bool = True


class McpSpec(BaseModel):
    description: str = Field(min_length=1, max_length=600)
    tools: list[McpTool] = Field(min_length=1)
    env_requirements: list[McpEnvRequirement] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list, description="pip package names from the allowed list")
    notes: str = ""


class StaticIssue(BaseModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    path: str | None = None


def check_python_source(path: str, source: str, *, network_allowed: bool) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [
            StaticIssue(
                level="error", code="python_syntax", message=f"{path}: {exc.msg} (line {exc.lineno})", path=path
            )
        ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                top = name.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    issues.append(
                        StaticIssue(
                            level="error",
                            code="forbidden_import",
                            message=f"{path}: import of {top!r} is not allowed",
                            path=path,
                        )
                    )
                elif top and top not in ALLOWED_TOP_LEVEL_IMPORTS and not top.startswith("_"):
                    issues.append(
                        StaticIssue(
                            level="error",
                            code="unknown_import",
                            message=f"{path}: import of {top!r} is not in the allowed list",
                            path=path,
                        )
                    )
                elif top in NETWORK_MODULES and not network_allowed:
                    issues.append(
                        StaticIssue(
                            level="error",
                            code="network_not_declared",
                            message=f"{path}: uses {top!r} but the step does not declare network access",
                            path=path,
                        )
                    )
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name in FORBIDDEN_CALLS:
                issues.append(
                    StaticIssue(
                        level="error",
                        code="forbidden_call",
                        message=f"{path}: call to {name}() is not allowed",
                        path=path,
                    )
                )
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "os"
                and fn.attr
                in ("system", "popen", "execv", "execvp", "spawn", "fork", "kill", "remove", "unlink", "rmdir")
            ):
                level = "error" if fn.attr in ("system", "popen", "execv", "execvp", "fork", "kill") else "warning"
                hint = "forbidden" if level == "error" else "destructive; make sure dry_run guards it"
                issues.append(
                    StaticIssue(
                        level=level,
                        code="dangerous_os_call",
                        message=f"{path}: os.{fn.attr} is {hint}",
                        path=path,
                    )
                )
    if SECRET_RE.search(source):
        issues.append(
            StaticIssue(
                level="error", code="secret_detected", message=f"{path}: looks like a hard-coded secret", path=path
            )
        )
    if "def run(" not in source:
        issues.append(
            StaticIssue(level="error", code="missing_run", message=f"{path}: must define run(**kwargs)", path=path)
        )
    return issues
