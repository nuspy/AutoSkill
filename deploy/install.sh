#!/usr/bin/env bash
# AutoSkill server installer (no Docker). Tested on Debian/Ubuntu with Python >= 3.11 and Node >= 20.
# Usage: sudo ./deploy/install.sh [/opt/autoskill]
# Environment switches (used by deploy/smoke.sh and CI): AUTOSKILL_SKIP_SYSTEMD=1 (no service user, no
# units), AUTOSKILL_SKIP_FRONTEND=1 (do not build the frontend), AUTOSKILL_USER=<service user>.
set -euo pipefail

TARGET="${1:-/opt/autoskill}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${AUTOSKILL_USER:-autoskill}"
SKIP_SYSTEMD="${AUTOSKILL_SKIP_SYSTEMD:-0}"
SKIP_FRONTEND="${AUTOSKILL_SKIP_FRONTEND:-0}"

echo "==> Installing AutoSkill into ${TARGET} (service user: ${SERVICE_USER})"
if [ "${SKIP_SYSTEMD}" != "1" ]; then
  id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd --system --create-home --home-dir "${TARGET}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi
mkdir -p "${TARGET}"/{app,data,frontend}

echo "==> Syncing application files"
sync_tree() {  # sync_tree <src/> <dest/>: rsync when available, otherwise a clean copy
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude ".venv" --exclude "node_modules" --exclude "__pycache__" "$1" "$2"
  else
    rm -rf "$2" && mkdir -p "$2" && cp -a "$1". "$2"
    find "$2" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
    rm -rf "$2/.venv" "$2/node_modules"
  fi
}
sync_tree "${REPO_DIR}/backend/" "${TARGET}/app/"
sync_tree "${REPO_DIR}/packages/" "${TARGET}/app/packages/"

echo "==> Python virtual environment"
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}" PIP_RETRIES="${PIP_RETRIES:-5}" PIP_DISABLE_PIP_VERSION_CHECK=1
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
AUTOSKILL_CORS_ORIGINS='["http://localhost"]'
AUTOSKILL_COOKIE_SECURE=false
# Outgoing email: console (log only), smtp, none
AUTOSKILL_EMAIL_BACKEND=console
# AUTOSKILL_SMTP_HOST=smtp.example.com
# AUTOSKILL_SMTP_PORT=587
# AUTOSKILL_SMTP_USERNAME=
# AUTOSKILL_SMTP_PASSWORD=
# AUTOSKILL_SMTP_STARTTLS=true
# AUTOSKILL_EMAIL_FROM="AutoSkill <no-reply@example.com>"
ENV
  chmod 600 "${TARGET}/autoskill.env"
fi

echo "==> Frontend build"
if [ "${SKIP_FRONTEND}" = "1" ]; then
  echo "(skipped: AUTOSKILL_SKIP_FRONTEND=1)"
elif command -v npm >/dev/null 2>&1; then
  (cd "${REPO_DIR}/frontend" && npm ci --no-audit --no-fund && npm run build)
  sync_tree "${REPO_DIR}/frontend/dist/" "${TARGET}/frontend/"
else
  echo "!! npm not found: skipping frontend build. Build it elsewhere and copy dist/ to ${TARGET}/frontend/"
fi

echo "==> Database migrations"
(cd "${TARGET}/app" && set -a && . "${TARGET}/autoskill.env" && set +a && "${TARGET}/venv/bin/alembic" upgrade head)

if [ "${SKIP_SYSTEMD}" = "1" ]; then
  echo "==> Done (systemd skipped). Start with: ${TARGET}/venv/bin/uvicorn autoskill.main:app --app-dir ${TARGET}/app"
  exit 0
fi
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
