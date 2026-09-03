#!/usr/bin/env bash
# AutoSkill server installer (no Docker). Tested on Debian/Ubuntu with Python >= 3.11 and Node >= 20.
# Usage: sudo ./deploy/install.sh [/opt/autoskill]
set -euo pipefail

TARGET="${1:-/opt/autoskill}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${AUTOSKILL_USER:-autoskill}"

echo "==> Installing AutoSkill into ${TARGET} (service user: ${SERVICE_USER})"
id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd --system --create-home --home-dir "${TARGET}" --shell /usr/sbin/nologin "${SERVICE_USER}"
mkdir -p "${TARGET}"/{app,data,frontend}

echo "==> Syncing application files"
rsync -a --delete --exclude ".venv" --exclude "node_modules" --exclude "__pycache__" "${REPO_DIR}/backend/" "${TARGET}/app/"
rsync -a --delete "${REPO_DIR}/packages/" "${TARGET}/app/packages/"

echo "==> Python virtual environment"
python3 -m venv "${TARGET}/venv"
"${TARGET}/venv/bin/pip" install --upgrade pip wheel >/dev/null
"${TARGET}/venv/bin/pip" install "${TARGET}/app"

echo "==> Building the autoskill-local wheel (served to agents at /dl/autoskill-local/)"
mkdir -p "${TARGET}/data/dist"
"${TARGET}/venv/bin/pip" wheel --no-deps -q -w "${TARGET}/data/dist" "${TARGET}/app/packages/autoskill-local"

if [ ! -f "${TARGET}/autoskill.env" ]; then
  echo "==> Creating ${TARGET}/autoskill.env (edit it before starting the services)"
  cat > "${TARGET}/autoskill.env" <<ENV
AUTOSKILL_ENV=prod
AUTOSKILL_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
# Single-process mode (no Redis): SQLite + inline jobs. Switch to Postgres + arq when you add a worker.
AUTOSKILL_DATABASE_URL=sqlite+aiosqlite:///${TARGET}/data/autoskill.db
AUTOSKILL_JOBS=inline
AUTOSKILL_EVENTS=memory
# With worker: uncomment and run autoskill-worker.service
# AUTOSKILL_DATABASE_URL=postgresql+asyncpg://autoskill:PASSWORD@localhost:5432/autoskill
# AUTOSKILL_REDIS_URL=redis://localhost:6379/0
# AUTOSKILL_JOBS=arq
# AUTOSKILL_EVENTS=redis
AUTOSKILL_DATA_DIR=${TARGET}/data
AUTOSKILL_PUBLIC_URL=http://localhost
AUTOSKILL_CORS_ORIGINS=["http://localhost"]
AUTOSKILL_COOKIE_SECURE=false
ENV
  chmod 600 "${TARGET}/autoskill.env"
fi

echo "==> Frontend build"
if command -v npm >/dev/null 2>&1; then
  (cd "${REPO_DIR}/frontend" && npm ci --no-audit --no-fund && npm run build)
  rsync -a --delete "${REPO_DIR}/frontend/dist/" "${TARGET}/frontend/"
else
  echo "!! npm not found: skipping frontend build. Build it elsewhere and copy dist/ to ${TARGET}/frontend/"
fi

echo "==> Database migrations"
(cd "${TARGET}/app" && set -a && . "${TARGET}/autoskill.env" && set +a && "${TARGET}/venv/bin/alembic" upgrade head)

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET}"

echo "==> systemd units"
sed "s#@TARGET@#${TARGET}#g; s#@USER@#${SERVICE_USER}#g" "${REPO_DIR}/deploy/autoskill-api.service" > /etc/systemd/system/autoskill-api.service
sed "s#@TARGET@#${TARGET}#g; s#@USER@#${SERVICE_USER}#g" "${REPO_DIR}/deploy/autoskill-worker.service" > /etc/systemd/system/autoskill-worker.service
systemctl daemon-reload
systemctl enable autoskill-api.service >/dev/null
systemctl restart autoskill-api.service

cat <<MSG

AutoSkill installed.
  API:       systemctl status autoskill-api     (listens on 127.0.0.1:8000)
  Worker:    systemctl enable --now autoskill-worker   (only in arq mode)
  Frontend:  static files in ${TARGET}/frontend  -> see deploy/nginx.conf
  Config:    ${TARGET}/autoskill.env
  Update:    re-run this script; it re-syncs files, rebuilds the frontend and migrates the database.
MSG
