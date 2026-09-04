#!/usr/bin/env bash
# Run AutoSkill on this machine: the API, the frontend, and the background worker when the
# configuration asks for one. Ctrl+C stops all of them; if one dies, the others follow.
#
# Run ./install.sh first.
#
#   ./start.sh                    API on :8000, UI on :5173
#   ./start.sh --backend-only     just the API (an already built frontend is served by nginx)
#   ./start.sh --api-port 9000    somewhere else
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="${VENV:-$ROOT/.venv}"
API_PORT="${AUTOSKILL_API_PORT:-8000}"
WEB_PORT="${AUTOSKILL_WEB_PORT:-5173}"
WANT_BACKEND=1
WANT_FRONTEND=1
WANT_WORKER=auto
RELOAD=1

usage() {
    cat <<'EOF'
Run AutoSkill on this machine: the API, the frontend, and the background worker when the
configuration asks for one. Ctrl+C stops all of them; if one dies, the others follow.

Run ./install.sh first.

  ./start.sh                    API on :8000, UI on :5173
  ./start.sh --backend-only     just the API (an already built frontend is served by nginx)
  ./start.sh --api-port 9000    somewhere else

Options:
  --backend-only       API (and worker) without the frontend dev server
  --frontend-only      frontend dev server alone, proxying to an API you started elsewhere
  --worker / --no-worker   force the arq worker on or off (default: on when AUTOSKILL_JOBS=arq)
  --api-port PORT      default 8000
  --web-port PORT      default 5173
  --no-reload          do not restart the API when a Python file changes
  --venv PATH          default ./.venv
  -h, --help           this text
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --backend-only) WANT_FRONTEND=0; shift ;;
        --frontend-only) WANT_BACKEND=0; WANT_WORKER=no; shift ;;
        --worker) WANT_WORKER=yes; shift ;;
        --no-worker) WANT_WORKER=no; shift ;;
        --api-port) API_PORT="$2"; shift 2 ;;
        --web-port) WEB_PORT="$2"; shift 2 ;;
        --no-reload) RELOAD=0; shift ;;
        --venv) VENV="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -d "$VENV/Scripts" ]; then BIN="$VENV/Scripts"; else BIN="$VENV/bin"; fi
PY="$BIN/python"
[ -x "$PY" ] || PY="$BIN/python.exe"
[ -x "$PY" ] || { echo "no virtualenv at $VENV — run ./install.sh first" >&2; exit 1; }

# The worker only earns its process when jobs actually go to Redis.
if [ "$WANT_WORKER" = auto ]; then
    if [ -f "$ROOT/backend/.env" ] && grep -qE '^[[:space:]]*AUTOSKILL_JOBS[[:space:]]*=[[:space:]]*arq' "$ROOT/backend/.env"; then
        WANT_WORKER=yes
    else
        WANT_WORKER=no
    fi
fi

# Job control gives every background job a process group of its own, so `kill -- -PID` takes the
# whole tree with it: `npm` is a launcher, and killing only it would leave the vite server it
# spawned holding the port.
set -m

pids=()
stopping=0

cleanup() {
    [ "$stopping" -eq 1 ] && return
    stopping=1
    for pid in "${pids[@]:-}"; do
        [ -n "$pid" ] || continue
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

launch() {
    local name="$1"; shift
    ( "$@" ) &
    pids+=("$!")
    printf '\033[1m==> %s\033[0m (pid %s)\n' "$name" "$!"
}

run_api() { cd "$ROOT/backend" && exec "$PY" -m uvicorn autoskill.main:app --port "$API_PORT" "$@"; }
run_worker() { cd "$ROOT/backend" && exec "$PY" -m autoskill.worker; }
run_web() { cd "$ROOT/frontend" && exec npm run dev -- --port "$WEB_PORT"; }

if [ "$WANT_BACKEND" -eq 1 ]; then
    if [ "$RELOAD" -eq 1 ]; then
        launch "API      http://localhost:$API_PORT  (docs at /docs)" run_api --reload
    else
        launch "API      http://localhost:$API_PORT  (docs at /docs)" run_api
    fi
fi
if [ "$WANT_WORKER" = yes ]; then
    launch "worker   arq" run_worker
fi
if [ "$WANT_FRONTEND" -eq 1 ]; then
    command -v npm >/dev/null 2>&1 || { echo "npm not found — run ./install.sh, or use --backend-only" >&2; exit 1; }
    [ -d "$ROOT/frontend/node_modules" ] || { echo "frontend/node_modules is missing — run ./install.sh" >&2; exit 1; }
    launch "UI       http://localhost:$WEB_PORT" run_web
fi

[ "${#pids[@]}" -gt 0 ] || { echo "nothing to start" >&2; exit 2; }
printf '\nCtrl+C stops everything.\n\n'

# `wait -n` (bash 4.3+) returns as soon as ANY child stops, so a backend that crashes does not
# leave a frontend behind pretending the stack is up. Older bash waits for all of them.
if ((BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 3))); then
    wait -n || true
    printf '\n\033[33mone process stopped — shutting the others down\033[0m\n'
else
    wait || true
fi
