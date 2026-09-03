.PHONY: setup backend-dev frontend-dev worker test test-backend test-local test-frontend lint typecheck migrate local-wheel ci

PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

setup:              ## create the backend venv, install backend + local package, frontend deps
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip wheel
	$(BIN)/pip install -e "backend[dev]" -e "packages/autoskill-local[dev]"
	cd frontend && npm ci

backend-dev:        ## API with auto-reload (SQLite, inline jobs)
	cd backend && ../$(BIN)/uvicorn autoskill.main:app --reload --port 8000

worker:             ## arq worker (only with AUTOSKILL_JOBS=arq)
	cd backend && ../$(BIN)/python -m autoskill.worker

frontend-dev:
	cd frontend && npm run dev

migrate:
	cd backend && ../$(BIN)/alembic upgrade head

local-wheel:        ## build the autoskill-local wheel served at /dl/autoskill-local/ (DIST defaults to data/dist)
	$(BIN)/pip wheel --no-deps -w $${DIST:-backend/data/dist} packages/autoskill-local

test: test-backend test-local test-frontend

test-backend:
	$(BIN)/python -m pytest -q backend

test-local:
	$(BIN)/python -m pytest -q packages/autoskill-local/tests

test-frontend:
	cd frontend && npm test -- --run

lint:
	$(BIN)/ruff check backend/autoskill backend/tests packages/autoskill-local
	cd frontend && npm run lint && npm run i18n:check

typecheck:
	cd frontend && npm run typecheck

ci: lint typecheck test
