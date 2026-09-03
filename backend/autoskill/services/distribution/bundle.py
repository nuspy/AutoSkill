"""Install bundles: everything an agent needs to install a skill, reachable from one online URL.

A bundle is built for a (skill, version) pair and a *base URL* under which all its files are served
(see api/dl.py): `INSTALL.<target>.md`, `install.json`, `skill.zip`, `mcp/<name>.zip`,
`components/<slug>/<file>`. The same structure is embedded in the skill zip as `autoskill.json`, and
the Markdown is rendered from it by the target adapters, so the person, the CLI and the agent read
one description with the same absolute URLs.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoskill.config import get_settings
from autoskill.core.crypto import decrypt, encrypt
from autoskill.core.security import generate_opaque_token, hash_token
from autoskill.db.base import utcnow
from autoskill.models.hub import DownloadGrant
from autoskill.models.mcp import McpServerVersion
from autoskill.models.project import Project
from autoskill.models.skill import Skill
from autoskill.models.skill_version import LibraryComponent, SkillVersion
from autoskill.models.trial import TrialSession
from autoskill.schemas.bundle import (
    ArtifactRef,
    CompanionEntry,
    ComponentEntry,
    EnvRequirement,
    InstallBundle,
    InstallMethod,
    McpRegistration,
    McpServerEntry,
    SkillEntry,
    TrialEntry,
)
from autoskill.services.library.catalog import components_for_version
from autoskill.services.packaging.skill_package import SkillPackage
from autoskill.services.packaging.store import load_package
from autoskill.services.targets import get_adapter, list_targets
from autoskill.services.targets.base import InstallContext, McpServerSpec

COMPANION_PACKAGE = "autoskill-local"
COMPANION_ENV = [
    EnvRequirement(name="AUTOSKILL_URL", description="AutoSkill server URL", secret=False),
    EnvRequirement(
        name="AUTOSKILL_API_KEY",
        description="key from `autoskill login` or a project API key (telemetry:write)",
        secret=True,
    ),
]
TRIAL_ENV = EnvRequirement(
    name="AUTOSKILL_SESSION_TOKEN", description="trial session token shown in the AutoSkill UI", secret=True
)
OPEN_TRIAL_STATES = ("requested", "installing", "installed", "testing", "suspended", "reviewing")


# --- URLs -------------------------------------------------------------------------------


def public_url() -> str:
    return get_settings().public_url.rstrip("/")


def grant_base_url(token: str) -> str:
    return f"{public_url()}/dl/{token}"


def hub_base_url(project_slug: str, skill_name: str, version: str) -> str:
    return f"{public_url()}/dl/hub/{project_slug}/{skill_name}/{version}"


# --- companion wheel --------------------------------------------------------------------

_WHEEL_RE = re.compile(r"^autoskill_local-(?P<ver>[0-9][^-]*)-py3-none-any\.whl$")


def _version_key(ver: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.+-]", ver))


def companion_wheel() -> Path | None:
    """The newest built wheel of autoskill-local under settings.dist_dir, if any."""
    root = get_settings().dist_dir
    if not root.exists():
        return None
    found = [(m.group("ver"), p) for p in root.glob("*.whl") if (m := _WHEEL_RE.match(p.name))]
    if not found:
        return None
    found.sort(key=lambda t: _version_key(t[0]))
    return found[-1][1]


def companion_entry() -> CompanionEntry:
    wheel = companion_wheel()
    if wheel is None:
        return CompanionEntry(env_requirements=COMPANION_ENV)
    data = wheel.read_bytes()
    url = f"{public_url()}/dl/autoskill-local/{wheel.name}"
    return CompanionEntry(
        version=_WHEEL_RE.match(wheel.name).group("ver"),  # type: ignore[union-attr]
        wheel=ArtifactRef(url=url, filename=wheel.name, sha256=hashlib.sha256(data).hexdigest(), size=len(data)),
        pip_spec=url,
        install_command=f"pipx install {url}",
        env_requirements=COMPANION_ENV,
    )


# --- artifacts --------------------------------------------------------------------------


def _zip_root_files(files: dict[str, bytes]) -> bytes:
    """Deterministic zip with the files at the archive root (pip-installable when it holds pyproject.toml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            zf.writestr(info, content)
    return buf.getvalue()


def mcp_zip(mv: McpServerVersion) -> bytes:
    from autoskill.services.mcpgen.generator import load_mcp_files

    return _zip_root_files(load_mcp_files(mv))


async def generated_mcp(session: AsyncSession, version: SkillVersion) -> McpServerVersion | None:
    return (
        await session.execute(select(McpServerVersion).where(McpServerVersion.skill_version_id == version.id))
    ).scalar_one_or_none()


def _env(items: list[dict]) -> list[EnvRequirement]:
    out = []
    for e in items or []:
        if isinstance(e, dict) and e.get("name"):
            out.append(
                EnvRequirement(name=e["name"], description=e.get("description", ""), secret=bool(e.get("secret")))
            )
    return out


def component_install(comp: LibraryComponent, download_url: str | None) -> InstallMethod:
    """Derive how to install a catalog component from its source/install/artifact records."""
    install = comp.install or {}
    source = comp.source or {}
    method = install.get("method")
    stype = source.get("type")
    if method is None:
        if comp.artifact and comp.kind == "mcp_server":
            method = "pipx_archive"
        elif comp.artifact:
            method = "copy"
        elif stype == "pip":
            method = "pipx"
        elif stype == "npm":
            method = "npm"
        elif stype == "git_url":
            method = "git"
        elif stype == "url":
            method = "binary"
        else:
            method = "manual"
    notes = install.get("hint", "")
    if method == "pipx_archive":
        spec = download_url or source.get("url")
        return InstallMethod(method=method, command=f"pipx install {spec}" if spec else "", spec=spec, notes=notes)
    if method in ("pipx", "pip"):
        spec = source.get("package") or comp.slug
        extra = f" --index-url {source['index_url']}" if source.get("index_url") else ""
        return InstallMethod(method=method, command=f"{method} install {spec}{extra}", spec=spec, notes=notes)
    if method == "npm":
        spec = source.get("package") or comp.slug
        return InstallMethod(method=method, command=f"npm install -g {spec}", spec=spec, notes=notes)
    if method == "git":
        url = source.get("url", "")
        ref = f"@{source['ref']}" if source.get("ref") else ""
        sub = f"#subdirectory={source['subdir']}" if source.get("subdir") else ""
        return InstallMethod(method=method, command=f"pipx install git+{url}{ref}{sub}", spec=url, notes=notes)
    if method == "copy":
        return InstallMethod(
            method=method,
            command=f"unzip {download_url or comp.slug + '.zip'} and copy the folder into the agent skills directory",
            spec=download_url,
            notes=notes,
        )
    if method == "binary":
        url = download_url or source.get("url")
        return InstallMethod(method=method, command=f"download {url} and put it on your PATH", spec=url, notes=notes)
    return InstallMethod(method="manual", command=notes or comp.description, spec=source.get("url"), notes=notes)


def _component_download(comp: LibraryComponent, base_url: str) -> ArtifactRef | None:
    if comp.artifact:
        a = comp.artifact
        return ArtifactRef(
            url=f"{base_url}/components/{comp.slug}/{a['filename']}",
            filename=a["filename"],
            sha256=a.get("sha256"),
            size=a.get("size"),
            content_type=a.get("content_type", "application/zip"),
        )
    url = (comp.source or {}).get("url")
    if url and (comp.source or {}).get("type") in ("url", "package_upload"):
        return ArtifactRef(
            url=url, filename=url.rsplit("/", 1)[-1] or comp.slug, content_type="application/octet-stream"
        )
    return None


def _component_paths(comp: LibraryComponent) -> dict[str, str]:
    paths = dict(comp.install_paths or {})
    for t in list_targets():
        paths.setdefault(t["id"], f"{t['global_skill_dir']}/{comp.slug}")
    return paths


def _snippets(spec: McpServerSpec) -> dict[str, str]:
    out = {}
    for t in list_targets():
        try:
            out[t["id"]] = get_adapter(t["id"]).mcp_config_snippet(spec)
        except NotImplementedError:  # pragma: no cover
            continue
    return out


def _spec_for(entry_name: str, reg: McpRegistration, description: str, install_hint: str) -> McpServerSpec:
    return McpServerSpec(
        name=entry_name,
        command=reg.command,
        args=list(reg.args),
        url=reg.url,
        env_requirements=[e.model_dump() for e in reg.env_requirements],
        description=description,
        install_hint=install_hint,
    )


AGENT_INSTRUCTIONS = [
    "Fetch `install.json` from the manifest URL above; it lists every file with its URL and SHA-256.",
    "Download each artifact and verify its checksum before using it. Never run anything that does not match.",
    "Install in this order: shared components, MCP servers (companion, generated tools, catalog servers), "
    "then copy the skill folder.",
    "Register every MCP server in the agent configuration with the snippet for your agent; ask the person "
    "for the environment values (never store them in the skill folder).",
    "Secrets and tokens are not in this bundle: the person gives you the API key / trial token.",
]


# --- bundle -----------------------------------------------------------------------------


async def build_bundle(
    session: AsyncSession,
    *,
    skill: Skill,
    version: SkillVersion,
    base_url: str,
    kind: str,
    trial: TrialSession | None = None,
    expires_at=None,
    default_target: str | None = None,
) -> InstallBundle:
    settings = get_settings()
    project = await session.get(Project, skill.project_id)
    targets = list_targets()
    target_ids = [t["id"] for t in targets]
    default_target = default_target or (trial.target_agent if trial else "hermes")
    server_name = f"{skill.name}-tools"

    companion = companion_entry()
    companion_env = list(COMPANION_ENV) + ([TRIAL_ENV] if trial else [])
    companion_reg = McpRegistration(command=companion.command, args=[], env_requirements=companion_env)
    companion_spec = _spec_for(
        "autoskill-companion", companion_reg, "checkpoints and run telemetry for AutoSkill", companion.install_command
    )
    mcp_servers = [
        McpServerEntry(
            name="autoskill-companion",
            kind="companion",
            description="checkpoints and run telemetry for AutoSkill",
            version=companion.version,
            download=companion.wheel,
            install=InstallMethod(method="pipx", command=companion.install_command, spec=companion.pip_spec),
            registration=companion_reg,
            snippets=_snippets(companion_spec),
        )
    ]

    mv = await generated_mcp(session, version)
    if mv is not None:
        data = mcp_zip(mv)
        url = f"{base_url}/mcp/{server_name}.zip"
        reg = McpRegistration(command=server_name, args=[], env_requirements=_env(mv.env_requirements))
        spec = _spec_for(
            server_name, reg, f"deterministic tools for {skill.title} ({len(mv.tools)} tools)", f"pipx install {url}"
        )
        mcp_servers.append(
            McpServerEntry(
                name=server_name,
                kind="generated",
                description=f"deterministic tools for {skill.title} ({len(mv.tools)} tools)",
                version=f"{mv.version}+build{mv.build}",
                download=ArtifactRef(
                    url=url, filename=f"{server_name}.zip", sha256=hashlib.sha256(data).hexdigest(), size=len(data)
                ),
                install=InstallMethod(method="pipx_archive", command=f"pipx install {url}", spec=url),
                registration=reg,
                snippets=_snippets(spec),
                tools=list(mv.tools),
            )
        )

    components: list[ComponentEntry] = []
    for dep, comp in await components_for_version(session, version.id):
        download = _component_download(comp, base_url)
        install = component_install(comp, download.url if download else None)
        if comp.kind == "mcp_server":
            ci = comp.install or {}
            reg = McpRegistration(
                command=ci.get("command") or comp.slug,
                args=list(ci.get("args", [])),
                url=ci.get("url"),
                env_requirements=_env(comp.env_requirements),
            )
            label = f"{comp.name}: {comp.description}" if comp.name.lower() != comp.slug else comp.description
            spec = _spec_for(comp.slug, reg, label, install.command)
            mcp_servers.append(
                McpServerEntry(
                    name=comp.slug,
                    kind="library",
                    description=label,
                    version=comp.version,
                    download=download,
                    install=install,
                    registration=reg,
                    snippets=_snippets(spec),
                    tools=list(comp.tools),
                    docs=comp.docs,
                )
            )
        else:
            components.append(
                ComponentEntry(
                    slug=comp.slug,
                    kind="plugin" if comp.kind == "plugin" else "skill",
                    name=comp.name,
                    version=comp.version,
                    description=comp.description,
                    reason=dep.reason or "",
                    download=download,
                    install=install,
                    install_paths=_component_paths(comp),
                    env_requirements=_env(comp.env_requirements),
                    docs=comp.docs,
                )
            )

    git_url = None
    if project and version.state in ("published", "superseded"):
        git_url = f"{public_url()}/git/{project.slug}/{skill.name}.git"
    skill_entry = SkillEntry(
        skill_id=skill.id,
        version_id=version.id,
        name=skill.name,
        title=skill.title,
        version=version.version,
        build=version.build,
        description=(version.frontmatter or {}).get("description", ""),
        download=ArtifactRef(url=f"{base_url}/skill.zip", filename=f"{skill.name}-{version.version}.zip"),
        git_url=git_url,
        signature=version.signature,
        files=list((version.manifest or {}).get("files", [])),
        install_paths={
            t["id"]: [p.replace("<skill-name>", skill.name) for p in get_adapter(t["id"]).skill_install_paths()]
            for t in targets
        },
    )
    trial_entry = None
    if trial is not None:
        trial_entry = TrialEntry(
            session_id=trial.id,
            mode=trial.mode,
            purpose=trial.purpose,
            target_agent=trial.target_agent,
            installed_callback_url=f"{public_url()}/api/v1/trials/{trial.id}/installed",
        )
    return InstallBundle(
        kind=kind,  # type: ignore[arg-type]
        server_url=settings.public_url,
        bundle_url=f"{base_url}/INSTALL.md",
        manifest_url=f"{base_url}/install.json",
        install_md_urls={t: f"{base_url}/INSTALL.{t}.md" for t in target_ids},
        generated_at=utcnow(),
        expires_at=expires_at,
        default_target=default_target,
        targets=target_ids,
        skill=skill_entry,
        companion=companion,
        mcp_servers=mcp_servers,
        components=components,
        trial=trial_entry,
        agent_instructions=AGENT_INSTRUCTIONS
        + (
            ["When done, POST to the trial callback URL with the trial token so the person can start testing."]
            if trial
            else []
        ),
    )


def install_context(bundle: InstallBundle, target: str, project_slug: str = "") -> InstallContext:
    """Render-ready context for TargetAdapter.render_install_md, derived from the bundle."""
    specs: list[McpServerSpec] = []
    for m in bundle.mcp_servers:
        specs.append(
            McpServerSpec(
                name=m.name,
                command=m.registration.command,
                args=list(m.registration.args),
                url=m.registration.url,
                env_requirements=[e.model_dump() for e in m.registration.env_requirements],
                description=m.description,
                install_hint=m.install.command,
                kind=m.kind,
                download_url=m.download.url if m.download else None,
                sha256=m.download.sha256 if m.download else None,
                install_command=m.install.command,
                docs=m.docs,
            )
        )
    deps = [
        {
            "slug": c.slug,
            "name": c.name,
            "kind": c.kind,
            "version": c.version,
            "reason": c.reason,
            "install_hint": c.install.notes or c.install.command or c.description,
            "install_command": c.install.command if c.install.method != "copy" else "",
            "download_url": c.download.url if c.download else None,
            "sha256": c.download.sha256 if c.download else None,
            "install_path": c.install_paths.get(target),
            "docs": c.docs,
            "env_requirements": [e.model_dump() for e in c.env_requirements],
        }
        for c in bundle.components
    ]
    return InstallContext(
        skill_name=bundle.skill.name,
        skill_title=bundle.skill.title,
        version=bundle.skill.version,
        server_url=bundle.server_url,
        project_slug=project_slug,
        mcp_servers=specs,
        dependencies=deps,
        trial=bundle.trial is not None,
        zip_url=bundle.skill.download.url,
        git_url=bundle.skill.git_url.split("://", 1)[-1] if bundle.skill.git_url else None,
        bundle_url=bundle.install_md_urls.get(target, bundle.bundle_url),
        manifest_url=bundle.manifest_url,
        build=bundle.skill.build,
        companion_wheel_url=bundle.companion.wheel.url if bundle.companion.wheel else None,
        companion_install_command=bundle.companion.install_command,
        artifacts=bundle.artifacts(),
        agent_instructions=list(bundle.agent_instructions),
        trial_session_id=bundle.trial.session_id if bundle.trial else None,
        installed_callback_url=bundle.trial.installed_callback_url if bundle.trial else None,
        expires_at=bundle.expires_at.isoformat(timespec="minutes") if bundle.expires_at else None,
    )


def render_install_md(bundle: InstallBundle, target: str, project_slug: str = "") -> str:
    return get_adapter(target).render_install_md(install_context(bundle, target, project_slug))


def bundle_json(bundle: InstallBundle) -> bytes:
    return json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False).encode()


async def skill_zip(
    session: AsyncSession,
    skill: Skill,
    version: SkillVersion,
    bundle: InstallBundle,
    *,
    trial: TrialSession | None = None,
    targets: list[str] | None = None,
) -> bytes:
    """The skill package plus INSTALL docs, autoskill.json (= install.json) and the generated MCP files."""
    pkg = load_package(skill.name, version)
    if trial is not None:
        fm = pkg.frontmatter()
        fm.setdefault("metadata", {})["autoskill_trial"] = trial.id
        fm["metadata"]["build"] = str(version.build)
        pkg.set_frontmatter(fm)
    project = await session.get(Project, skill.project_id)
    slug = project.slug if project else ""
    extra: dict[str, bytes] = {}
    for target in targets or bundle.targets:
        try:
            extra[f"INSTALL.{target}.md"] = render_install_md(bundle, target, slug).encode()
        except KeyError:
            continue
    extra["autoskill.json"] = bundle_json(bundle)
    mv = await generated_mcp(session, version)
    if mv is not None:
        from autoskill.services.mcpgen.generator import load_mcp_files

        for path, content in load_mcp_files(mv).items():
            extra[f"mcp/{skill.name}-tools/{path}"] = content
    return pkg.to_zip(extra)


def package_from_zip(data: bytes) -> SkillPackage:  # convenience for tests
    return SkillPackage.from_zip(data)


# --- grants -----------------------------------------------------------------------------


async def create_grant(
    session: AsyncSession,
    *,
    skill: Skill,
    version: SkillVersion,
    kind: str,
    created_by: str | None,
    trial: TrialSession | None = None,
    expires_in_days: int | None = None,
    label: str | None = None,
    target_agent: str | None = None,
) -> tuple[DownloadGrant, str]:
    token = generate_opaque_token(32)
    expires_at = None
    if kind == "version":
        days = expires_in_days or get_settings().download_link_days
        expires_at = utcnow() + timedelta(days=days)
    grant = DownloadGrant(
        kind=kind,
        token_hash=hash_token(token),
        token_encrypted=encrypt(token),
        skill_id=skill.id,
        skill_version_id=version.id,
        trial_session_id=trial.id if trial else None,
        target_agent=target_agent or (trial.target_agent if trial else None),
        created_by=created_by,
        label=label,
        expires_at=expires_at,
    )
    session.add(grant)
    await session.flush()
    return grant, token


def grant_token(grant: DownloadGrant) -> str:
    return decrypt(grant.token_encrypted)


def grant_urls(grant: DownloadGrant) -> tuple[str, str]:
    base = grant_base_url(grant_token(grant))
    return f"{base}/INSTALL.md", f"{base}/install.json"


async def trial_grant(session: AsyncSession, trial: TrialSession) -> DownloadGrant | None:
    return (
        await session.execute(
            select(DownloadGrant)
            .where(DownloadGrant.trial_session_id == trial.id, DownloadGrant.revoked_at.is_(None))
            .order_by(DownloadGrant.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def grant_active(grant: DownloadGrant, trial: TrialSession | None) -> bool:
    now = utcnow()
    if grant.revoked_at is not None:
        return False
    if grant.expires_at is not None and grant.expires_at < now:
        return False
    if grant.kind == "trial":
        if trial is None:
            return False
        return trial.state in OPEN_TRIAL_STATES or bool(trial.keep_installed)
    return True


__all__ = [
    "AGENT_INSTRUCTIONS",
    "build_bundle",
    "bundle_json",
    "companion_entry",
    "companion_wheel",
    "component_install",
    "create_grant",
    "generated_mcp",
    "grant_active",
    "grant_base_url",
    "grant_token",
    "grant_urls",
    "hub_base_url",
    "install_context",
    "mcp_zip",
    "render_install_md",
    "skill_zip",
    "trial_grant",
]
