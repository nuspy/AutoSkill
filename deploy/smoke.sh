#!/usr/bin/env bash
# Smoke test of the installer on a clean prefix, without systemd/nginx: installs, starts the API,
# checks health, the migration, and that the autoskill-local wheel is served at /dl/autoskill-local/.
# Usage: ./deploy/smoke.sh [prefix]   (default: a temporary directory)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${1:-$(mktemp -d /tmp/autoskill-smoke.XXXXXX)}"
PORT="${AUTOSKILL_SMOKE_PORT:-8765}"

AUTOSKILL_SKIP_SYSTEMD=1 AUTOSKILL_SKIP_FRONTEND="${AUTOSKILL_SKIP_FRONTEND:-1}" bash "${REPO_DIR}/deploy/install.sh" "${PREFIX}"

set -a; . "${PREFIX}/autoskill.env"; set +a
export AUTOSKILL_PUBLIC_URL="http://127.0.0.1:${PORT}"
"${PREFIX}/venv/bin/uvicorn" autoskill.main:app --app-dir "${PREFIX}/app" --host 127.0.0.1 --port "${PORT}" >"${PREFIX}/api.log" 2>&1 &
API_PID=$!
trap 'kill ${API_PID} 2>/dev/null || true' EXIT

for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" | grep -q '"ok"' || { echo "health check failed"; cat "${PREFIX}/api.log"; exit 1; }

wheel=$(ls "${PREFIX}"/data/dist/autoskill_local-*.whl | head -n1)
[ -n "${wheel}" ] || { echo "wheel not built"; exit 1; }
status=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/dl/autoskill-local/latest")
[ "${status}" = "302" ] || { echo "expected 302 from /dl/autoskill-local/latest, got ${status}"; cat "${PREFIX}/api.log"; exit 1; }
curl -fsS -o "${PREFIX}/downloaded.whl" "http://127.0.0.1:${PORT}/dl/autoskill-local/$(basename "${wheel}")"
cmp -s "${wheel}" "${PREFIX}/downloaded.whl" || { echo "served wheel differs"; exit 1; }
echo "smoke test OK (prefix ${PREFIX})"
