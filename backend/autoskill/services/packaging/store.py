"""Persist and load SkillPackages through the content store using the version manifest."""

from __future__ import annotations

from autoskill.models.skill_version import SkillVersion
from autoskill.services.packaging.skill_package import SkillPackage
from autoskill.services.storage.content_store import get_content_store


def store_package(version: SkillVersion, pkg: SkillPackage) -> None:
    store = get_content_store()
    for content in pkg.files.values():
        store.put(content)
    version.manifest = pkg.manifest()
    version.frontmatter = pkg.frontmatter()
    version.signature = pkg.sign()


def load_package(name: str, version: SkillVersion) -> SkillPackage:
    store = get_content_store()
    pkg = SkillPackage(name=name)
    for entry in version.manifest.get("files", []):
        pkg.files[entry["path"]] = store.get(entry["hash"])
    return pkg
