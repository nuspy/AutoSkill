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

## Local development

```bash
make setup            # backend venv (uv) + frontend npm install
cp .env.example backend/.env
make backend-dev      # API with reload on http://localhost:8000  (docs at /docs)
make frontend-dev     # UI on http://localhost:5173 (proxies /api to the backend)
make test             # pytest + vitest
make lint             # ruff + eslint
```

The first account registered in the UI becomes the administrator. Development uses SQLite, inline
background jobs and in-memory events, so no database server or Redis is required.

## Server deployment

See [`deploy/README.md`](deploy/README.md). Short version: `sudo ./deploy/install.sh /opt/autoskill`,
edit `/opt/autoskill/autoskill.env`, enable nginx with `deploy/nginx.conf`.

## Status

Phase 0 (foundation): authentication with roles (admin / reviewer / member), projects and members,
project API keys, device connection for the CLI (device-code flow), notifications with server-sent
events, background job runner, admin area, audit log. Next phases follow the product plan:
interview + per-skill memory, drafting + packaging, local trial with the companion MCP,
versioning + review, Skill Hub, MCP generation, improvement loop.
