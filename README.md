# AutoSkill

AutoSkill lets a non-technical worker explain a recurring task to an AI agent, turn it into an
**agent skill** (the open [Agent Skills](https://agentskills.io) `SKILL.md` format used by Hermes,
OpenClaw, Claude Code, Codex and Antigravity), test it **step by step on their own agent and machine**,
harden the known steps into an **MCP server**, and distribute versioned, reviewed skills through a
central **Skill Hub**. Every run of every skill is logged step by step, and failed runs feed an
improvement loop whose new versions are always authorized by a human.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI + SQLAlchemy 2 + Alembic API server and `arq` worker (Python 3.11+) |
| `frontend/` | React 18 + Vite + TypeScript + Tailwind single-page app, i18n (en, it, hu, de, es, fr) |
| `packages/` | `autoskill-local` (user-side CLI + companion MCP), skill and MCP templates |
| `deploy/` | Server installation without Docker: `install.sh`, systemd units, nginx site |
| `docs/` | Architecture, data model, state machines, security notes |

## Install and run

Two scripts at the root do everything — virtualenv, backend, the `autoskill-local` CLI, the
llmswitch provider library, the database schema, the agent wheel and the frontend dependencies.
Run the installer again after every pull: each step is idempotent.

```bash
./install.sh          # Linux, macOS, Git Bash
./start.sh            # API on :8000, UI on :5173, worker when the configuration asks for one
```

```powershell
.\install.ps1         # Windows PowerShell 5.1 or PowerShell 7
.\start.ps1
```

`install` picks up a `llmswitch` clone sitting next to this repository; point it somewhere else
with `--llmswitch <path-or-git-url>` / `-LlmSwitch`. It updates `node_modules` in place; ask for
`--clean-frontend` / `-CleanFrontend` to rebuild it from the lockfile, with the dev server stopped
(on Windows a `.node` binary a running server has loaded cannot be deleted). `start` takes `--backend-only`,
`--frontend-only`, `--api-port`, `--web-port`, `--no-reload` (and the `-BackendOnly` … equivalents);
`--help` / `Get-Help` lists them all. Ctrl+C stops every component, and if one dies the others are
shut down rather than left pretending the stack is up.

The `Makefile` covers the same ground in pieces for those who prefer it (`make setup`,
`make backend-dev`, `make frontend-dev`, `make test`, `make lint`).

The first account registered in the UI becomes the administrator. Development uses SQLite, inline
background jobs and in-memory events, so no database server or Redis is required.

## Choosing the model

Every generative step goes to the provider an administrator picked in *Administration → AI
providers*. The single source of that choice is the [`llmswitch`](docs/llm-providers.md) registry of
the machine the server runs on, installed by `./install.sh`: local engines that
respect the GPU's memory, pay-per-use API keys, subscriptions reused from an official CLI that is
already signed in, and the CLI agents themselves. Each stage — interviewer, supervisor, author,
coach, analyst — is pointed at one of them, or at the default.

API keys live in a file outside the repository, never in the database and never in the answers the
browser gets back. Details and failure modes in [`docs/llm-providers.md`](docs/llm-providers.md).

## Server deployment

See [`deploy/README.md`](deploy/README.md). Short version: `sudo ./deploy/install.sh /opt/autoskill`,
edit `/opt/autoskill/autoskill.env`, enable nginx with `deploy/nginx.conf`.

## How a skill is born

1. **Interview** (`/p/<project>/skills/new`): the worker describes the task; a deterministic procedure
   asks one question at a time until ten completeness gates pass (sources, steps, rules, exceptions,
   acceptance criteria, integrations, side effects) and the worker confirms the summary. The skill
   **memory** (rationale, business needs, how it is done today, technical and integration notes) is
   extracted automatically and kept for whoever maintains the skill.
2. **Draft**: the author model writes the content, code owns the structure: `SKILL.md` with step
   markers, side-effect labels, safety rules and the companion protocol; `references/`, `scripts/`.
   Every step gets a trial mode: read-only steps run for real, reversible steps run on a copy,
   irreversible steps are only simulated and always need explicit authorization.
3. **Trial on your own agent** (`autoskill trial install ...`): the skill is installed temporarily on
   the worker's machine. The agent calls the `autoskill-companion` MCP at every step: explain,
   preview with real data, (execute), verify. The person decides in the web UI (continue, change,
   discuss with the coach, redo, skip, stop, approve and authorize the next step). Changes patch the
   step instruction, rebuild the package and sync the installed copy. Trials can be suspended and
   resumed; any version can be re-tested at any time.
4. **Outcome**: accept (keep or remove the copy, version becomes *tested*), request changes (a new
   version is drafted from the corrections), major rework, or remove.

## Status

All planned phases are implemented and covered by tests (backend 58, local package 9, frontend unit + build):

| Area | What exists |
|---|---|
| Foundation | multi-user auth (admin / reviewer / member), projects and members, API keys, device login for the CLI, notifications + SSE, jobs (inline or arq), audit log, admin area |
| Providers | the machine's own, through llmswitch: local engines with the VRAM rule, pay-per-use keys, subscriptions reused from an authenticated CLI, CLI agents; assigned per purpose from the admin area, keys outside the repository |
| Interview | deterministic procedure engine with supervisor steps, one question per turn, ten completeness gates, knowledge document, per-skill memory |
| Drafting | Agent Skills packaging and validation, author model + code-owned SKILL.md, install guides for Hermes, OpenClaw, Claude Code, Codex, Antigravity, admin component library |
| Local trials | `autoskill` CLI + `autoskill-companion` MCP; phased checkpoints (explain / preview / execute / verify), simulation of irreversible steps, coach discussions patching the skill, suspend/resume, re-test any version, telemetry with redaction |
| Lifecycle | version state machine, review queue with checklist, human-only publish/deprecate authorizations, diffs and semver hints |
| Hub | shared catalog with visibility levels, search, categories, favorites, installations with update alerts, try-before-install, personal variants (forks), read-only git distribution per skill |
| MCP tools | generated MCP server per version from deterministic steps with dry-run and confirmation guards, static safety checks, local check via the CLI |
| Improvement | analysis of failed runs, issues and corrections; proposals with rationale; human accept/reject; daily scan |

Not yet done: translations beyond English and Italian (the other four locales fall back to English),
ratings, "contribute back" from a variant to its origin, e-mail notifications, browser end-to-end tests.

## Install bundles for agents

Each trial, download link and public skill exposes an online-reachable bundle under `/dl/...`:
`INSTALL.<agent>.md`, `install.json`, `skill.zip`, the generated MCP server and the catalog components the
skill depends on, all with absolute URLs and SHA-256 checksums, no login required. Hand the address to your
agent or run `autoskill install --from <install.json url>`. See `docs/local-testing.md`.

## Hub extras

Ratings and "top rated", curated lists (admin-picked groups of published skills), contributions from a
variant back to its original (accepted as a new draft that follows trial → review → publish), promotion
of a published hub skill to the component catalog, and an optional external git mirror pushed on every
publish. `AUTOSKILL_LLM_FAKE=demo` runs the whole product with canned model answers (used by the
Playwright suite: `cd frontend && npm run e2e`).
