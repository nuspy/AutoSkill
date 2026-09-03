# Architecture (Phase 0)

```
Browser (React SPA) ──REST + SSE──▶ FastAPI API ──SQLAlchemy──▶ SQLite / PostgreSQL
                                        │ jobs
User machine: autoskill CLI +           ▼
autoskill-companion MCP ──REST──▶ inline runner (single process) or arq worker via Redis
```

* **API** (`backend/autoskill`): routers under `api/v1`, services under `services/`, ORM models under
  `models/`. Errors are raised as `AppError` subclasses and rendered as `{"error": {"code", "message", "details"}}`
  so the frontend can translate them.
* **Jobs** (`core/jobs.py`): async functions registered with `@job("name")`. `AUTOSKILL_JOBS=inline` runs
  them as asyncio tasks in the API process; `AUTOSKILL_JOBS=arq` enqueues them on Redis for `autoskill.worker`.
  Every job has a row in `jobs` with progress, result and error.
* **Events** (`core/events.py`): per-user and per-project channels delivered as server-sent events
  (`/me/events`, `/projects/{id}/events`). In-memory bus by default, Redis pub/sub when `AUTOSKILL_EVENTS=redis`.
* **Auth**: argon2id passwords, 15-minute JWT access tokens, rotating refresh token in an HttpOnly cookie,
  device-code flow issuing user API keys for the CLI (`ask_...`), project API keys for telemetry.
* **Roles**: global `admin` / `reviewer` / `member`; per project `owner` / `editor` / `viewer`.
* **Content store** (`services/storage/content_store.py`): content-addressed blobs under `data/store/objects`.
