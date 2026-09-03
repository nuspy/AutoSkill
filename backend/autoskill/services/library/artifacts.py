"""Uploaded artifacts of library components (zip / wheel / sdist), validated and stored in the content store."""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile

from autoskill.core.errors import ValidationFailed
from autoskill.models.skill_version import LibraryComponent
from autoskill.services.packaging.skill_package import SkillPackage
from autoskill.services.storage.content_store import get_content_store

CONTENT_TYPES = {
    ".zip": "application/zip",
    ".whl": "application/zip",
    ".tar.gz": "application/gzip",
    ".tgz": "application/gzip",
}


def _extension(filename: str) -> str:
    lower = filename.lower()
    for ext in (".tar.gz", ".tgz", ".whl", ".zip"):
        if lower.endswith(ext):
            return ext
    return ""


def _archive_names(filename: str, data: bytes) -> list[str]:
    ext = _extension(filename)
    try:
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return [n for n in zf.namelist() if not n.endswith("/")]
        if ext in (".tar.gz", ".tgz"):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                return [m.name for m in tf.getmembers() if m.isfile()]
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise ValidationFailed("artifact_unreadable", message=f"archive cannot be read: {exc}") from None
    raise ValidationFailed("artifact_type", message="upload a .zip, .whl or .tar.gz file")


def validate_artifact(component: LibraryComponent, filename: str, data: bytes) -> dict:
    """Check the archive matches the component kind; return the artifact record (without storing)."""
    if not data:
        raise ValidationFailed("artifact_empty")
    names = _archive_names(filename, data)
    ext = _extension(filename)
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        raise ValidationFailed("artifact_paths", message="archive contains absolute or parent paths")
    if component.kind == "mcp_server":
        installable = ext == ".whl" or any(n.split("/")[-1] == "pyproject.toml" and n.count("/") <= 1 for n in names)
        if not installable and not any(n.split("/")[-1] == "package.json" and n.count("/") <= 1 for n in names):
            raise ValidationFailed(
                "artifact_not_installable",
                message=(
                    "an MCP server artifact must be a wheel, or an archive with pyproject.toml/package.json at its root"
                ),
            )
    elif component.kind == "skill":
        md = [n for n in names if n.split("/")[-1] == "SKILL.md" and n.count("/") <= 1]
        if not md or ext not in (".zip",):
            raise ValidationFailed("artifact_not_skill", message="a skill artifact is a zip with SKILL.md at its root")
        if ext == ".zip":
            pkg = SkillPackage.from_zip(data)
            report = pkg.validate()
            if not report.ok:
                raise ValidationFailed("artifact_skill_invalid", errors=[i.message for i in report.errors][:10])
            fm = pkg.frontmatter()
            if fm.get("name") and fm["name"] != component.slug:
                raise ValidationFailed(
                    "artifact_name_mismatch",
                    message=f"SKILL.md name {fm['name']!r} must equal the component slug {component.slug!r}",
                )
    return {
        "filename": filename.split("/")[-1],
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "content_type": CONTENT_TYPES.get(ext, "application/octet-stream"),
        "files": len(names),
    }


def store_artifact(component: LibraryComponent, filename: str, data: bytes) -> dict:
    record = validate_artifact(component, filename, data)
    record["hash"] = get_content_store().put(data)
    component.artifact = record
    return record


def load_artifact(component: LibraryComponent) -> tuple[dict, bytes]:
    if not component.artifact:
        raise ValidationFailed("no_artifact", message="this component has no uploaded artifact")
    return component.artifact, get_content_store().get(component.artifact["hash"])
