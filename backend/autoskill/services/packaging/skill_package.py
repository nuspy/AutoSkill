"""In-memory representation of a skill folder (Agent Skills spec) with validation, zip and manifest.

Spec reference: SKILL.md with YAML frontmatter; `name` 1-64 chars [a-z0-9-], no leading/trailing/double
hyphens, equal to the folder name; `description` 1-1024 chars; optional `license`, `compatibility`
(<= 500), `metadata` (string -> string), `allowed-tools`.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

from autoskill.config import get_settings

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ask_[a-f0-9]{8}_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
MAX_SKILL_MD_LINES = 500
MAX_SKILL_MD_TOKENS = 5000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".py",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".toml",
    ".js",
    ".ts",
    ".html",
    ".xml",
}


@dataclass
class ValidationIssue:
    level: str  # error | warning
    code: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "path": self.path}


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    def add(self, level: str, code: str, message: str, path: str | None = None) -> None:
        self.issues.append(ValidationIssue(level, code, message, path))

    def as_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.as_dict() for i in self.issues]}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split SKILL.md into (frontmatter dict, body). Raises ValueError on malformed input."""
    if not text.startswith("---"):
        raise ValueError("SKILL.md must start with YAML frontmatter ('---')")
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        raise ValueError("frontmatter is not closed with '---'")
    head = parts[0][3:]
    body = parts[1]
    if body.startswith("\n"):
        body = body[1:]
    data = yaml.safe_load(head) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    return data, body


def render_frontmatter(data: dict) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000).strip() + "\n---\n"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class SkillPackage:
    name: str
    files: dict[str, bytes] = field(default_factory=dict)  # path (posix, relative to skill root) -> bytes

    # --- construction ---------------------------------------------------------------

    @classmethod
    def from_files(cls, name: str, files: dict[str, str | bytes]) -> SkillPackage:
        pkg = cls(name=name)
        for path, content in files.items():
            pkg.write(path, content)
        return pkg

    @classmethod
    def from_zip(cls, data: bytes) -> SkillPackage:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            roots = {n.split("/", 1)[0] for n in names if "/" in n}
            root = roots.pop() if len(roots) == 1 and all("/" in n for n in names) else None
            pkg = cls(name=root or "skill")
            for n in names:
                rel = n.split("/", 1)[1] if root else n
                pkg.files[rel] = zf.read(n)
        return pkg

    def write(self, path: str, content: str | bytes) -> None:
        self.files[str(PurePosixPath(path))] = content.encode() if isinstance(content, str) else content

    def read_text(self, path: str) -> str:
        return self.files[path].decode()

    # --- accessors ------------------------------------------------------------------

    @property
    def skill_md(self) -> str:
        return self.read_text("SKILL.md")

    def frontmatter(self) -> dict:
        data, _ = parse_frontmatter(self.skill_md)
        return data

    def body(self) -> str:
        _, body = parse_frontmatter(self.skill_md)
        return body

    def set_frontmatter(self, data: dict) -> None:
        body = self.body() if "SKILL.md" in self.files else ""
        self.write("SKILL.md", render_frontmatter(data) + body)

    def total_size(self) -> int:
        return sum(len(b) for b in self.files.values())

    # --- validation -----------------------------------------------------------------

    def validate(self) -> ValidationReport:
        report = ValidationReport()
        if not NAME_RE.match(self.name) or len(self.name) > 64:
            report.add(
                "error",
                "invalid_name",
                f"skill name {self.name!r} must match [a-z0-9]+(-[a-z0-9]+)* and be <= 64 chars",
            )
        if "SKILL.md" not in self.files:
            report.add("error", "missing_skill_md", "SKILL.md is required")
            return report
        try:
            fm, body = parse_frontmatter(self.skill_md)
        except (ValueError, yaml.YAMLError) as exc:
            report.add("error", "bad_frontmatter", str(exc), "SKILL.md")
            return report
        name = fm.get("name")
        if not isinstance(name, str) or name != self.name:
            report.add(
                "error",
                "name_mismatch",
                f"frontmatter name {name!r} must equal the folder name {self.name!r}",
                "SKILL.md",
            )
        desc = fm.get("description")
        if not isinstance(desc, str) or not (1 <= len(desc.strip()) <= 1024):
            report.add("error", "bad_description", "description is required (1-1024 characters)", "SKILL.md")
        elif len(desc.strip()) < 40:
            report.add(
                "warning",
                "short_description",
                "description should say what the skill does AND when to use it",
                "SKILL.md",
            )
        compat = fm.get("compatibility")
        if compat is not None and (not isinstance(compat, str) or not (1 <= len(compat) <= 500)):
            report.add("error", "bad_compatibility", "compatibility must be 1-500 characters", "SKILL.md")
        meta = fm.get("metadata")
        if meta is not None:
            if not isinstance(meta, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in meta.items()
            ):
                report.add(
                    "error", "bad_metadata", "metadata must be a mapping of string keys to string values", "SKILL.md"
                )
        allowed = fm.get("allowed-tools")
        if allowed is not None and not isinstance(allowed, str):
            report.add("error", "bad_allowed_tools", "allowed-tools must be a space-separated string", "SKILL.md")
        for key, value in fm.items():
            if isinstance(value, str) and ("<" in value or ">" in value):
                report.add(
                    "warning", "angle_brackets", f"frontmatter field {key!r} contains angle brackets", "SKILL.md"
                )
        lines = body.count("\n") + 1
        if lines > MAX_SKILL_MD_LINES:
            report.add(
                "warning",
                "skill_md_too_long",
                f"SKILL.md body has {lines} lines (> {MAX_SKILL_MD_LINES}); move detail to references/",
                "SKILL.md",
            )
        if estimate_tokens(body) > MAX_SKILL_MD_TOKENS:
            report.add(
                "warning",
                "skill_md_too_many_tokens",
                "SKILL.md body exceeds ~5000 tokens; move detail to references/",
                "SKILL.md",
            )
        if not body.strip():
            report.add("error", "empty_body", "SKILL.md has no instructions", "SKILL.md")

        for path, content in self.files.items():
            p = PurePosixPath(path)
            if p.is_absolute() or ".." in p.parts:
                report.add("error", "bad_path", f"path {path!r} must be relative and inside the skill folder", path)
            if len(content) > MAX_FILE_BYTES:
                report.add("error", "file_too_large", f"{path} exceeds {MAX_FILE_BYTES} bytes", path)
            if p.suffix in TEXT_EXTENSIONS:
                try:
                    text = content.decode()
                except UnicodeDecodeError:
                    report.add("error", "not_utf8", f"{path} is not valid UTF-8", path)
                    continue
                for pattern in SECRET_PATTERNS:
                    if pattern.search(text):
                        report.add(
                            "error",
                            "secret_detected",
                            f"{path} appears to contain a secret; use env_requirements instead",
                            path,
                        )
                        break
                if p.suffix == ".py":
                    try:
                        compile(text, path, "exec")
                    except SyntaxError as exc:
                        report.add("error", "python_syntax", f"{path}: {exc.msg} (line {exc.lineno})", path)
        if self.total_size() > MAX_PACKAGE_BYTES:
            report.add("error", "package_too_large", "package exceeds 50 MiB")

        # referenced files must exist (relative links and bare paths like scripts/x.py)
        for ref in re.findall(r"\]\(([^)\s#]+)\)", body) + re.findall(
            r"\b((?:scripts|references|assets)/[\w./\-]+)", body
        ):
            if ref.startswith(("http://", "https://", "mailto:")):
                continue
            if ref not in self.files:
                report.add(
                    "error", "missing_reference", f"SKILL.md references {ref!r} which is not in the package", "SKILL.md"
                )
        return report

    # --- outputs --------------------------------------------------------------------

    def manifest(self) -> dict:
        files = [
            {"path": path, "hash": hashlib.sha256(content).hexdigest(), "size": len(content)}
            for path, content in sorted(self.files.items())
        ]
        return {"files": files, "total_size": self.total_size()}

    def sign(self) -> str:
        payload = json.dumps(self.manifest()["files"], sort_keys=True).encode()
        return hmac.new(get_settings().secret_key.encode(), payload, hashlib.sha256).hexdigest()

    def to_zip(self, extra_files: dict[str, bytes] | None = None) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, content in sorted({**self.files, **(extra_files or {})}.items()):
                info = zipfile.ZipInfo(f"{self.name}/{path}", date_time=(2020, 1, 1, 0, 0, 0))
                info.external_attr = (0o755 if path.endswith((".sh", ".py")) else 0o644) << 16
                zf.writestr(info, content)
        return buf.getvalue()

    def diff(self, other: SkillPackage) -> dict:
        """Return {added, removed, changed} paths relative to `other` (the older package)."""
        mine, theirs = self.manifest()["files"], other.manifest()["files"]
        m = {f["path"]: f["hash"] for f in mine}
        t = {f["path"]: f["hash"] for f in theirs}
        return {
            "added": sorted(set(m) - set(t)),
            "removed": sorted(set(t) - set(m)),
            "changed": sorted(p for p in set(m) & set(t) if m[p] != t[p]),
        }
