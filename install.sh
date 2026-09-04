#!/usr/bin/env bash
# Install every component of AutoSkill on this machine: the backend and its virtualenv, the
# `autoskill-local` CLI + companion MCP, the optional llmswitch provider library, the database
# schema, the wheel the server hands to agents, and the frontend dependencies.
#
# Run it again whenever you pull: every step is idempotent.
# For a Linux server with systemd and nginx, use deploy/install.sh instead.
#
#   ./install.sh                              everything, llmswitch from ../llmswitch if present
#   ./install.sh --llmswitch ../llmswitch     or from a path / git URL of your own
#   ./install.sh --skip-frontend              backend only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="${VENV:-$ROOT/.venv}"
LLMSWITCH="${LLMSWITCH:-}"
SKIP_FRONTEND=0
CLEAN_FRONTEND=0
SKIP_WHEEL=0

usage() {
    cat <<'EOF'
Install every component of AutoSkill on this machine: the backend and its virtualenv, the
autoskill-local CLI + companion MCP, the optional llmswitch provider library, the database
schema, the wheel the server hands to agents, and the frontend dependencies.

Run it again whenever you pull: every step is idempotent.
For a Linux server with systemd and nginx, use deploy/install.sh instead.

  ./install.sh                              everything, llmswitch from ../llmswitch if present
  ./install.sh --llmswitch ../llmswitch     or from a path / git URL of your own
  ./install.sh --skip-frontend              backend only

Options:
  --venv PATH          where the virtualenv goes (default: ./.venv)
  --llmswitch SOURCE   path or git URL of the llmswitch library
  --skip-frontend      do not touch frontend/node_modules
  --clean-frontend     rebuild node_modules from scratch (npm ci) instead of updating it
  --skip-wheel         do not build the autoskill-local wheel
  -h, --help           this text
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --venv) VENV="$2"; shift 2 ;;
        --llmswitch) LLMSWITCH="$2"; shift 2 ;;
        --skip-frontend) SKIP_FRONTEND=1; shift ;;
        --clean-frontend) CLEAN_FRONTEND=1; shift ;;
        --skip-wheel) SKIP_WHEEL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die() { printf '\033[31m  x %s\033[0m\n' "$*" >&2; exit 1; }

# --- Python 3.11+ ------------------------------------------------------------------------

find_python() {
    local candidate
    # Windows first: the `py` launcher knows the properly installed interpreters, while a bare
    # `python3.11` on the PATH can be a stripped-down build that cannot verify a TLS certificate.
    if command -v py >/dev/null 2>&1; then
        for candidate in -3.13 -3.12 -3.11; do
            if py "$candidate" -c '' >/dev/null 2>&1; then
                echo "py $candidate"
                return 0
            fi
        done
    fi
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

say "Python"
PYTHON="$(find_python)" || die "no Python 3.11+ found. Install one and run this again."
echo "  $($PYTHON -c 'import sys, platform; print(platform.python_version(), "at", sys.executable)')"

# --- virtualenv --------------------------------------------------------------------------

say "Virtualenv ($VENV)"
if [ ! -x "$VENV/bin/python" ] && [ ! -x "$VENV/Scripts/python.exe" ]; then
    $PYTHON -m venv "$VENV"
    echo "  created"
else
    echo "  already there"
fi
# Git Bash on Windows gets a venv laid out the Windows way.
if [ -d "$VENV/Scripts" ]; then BIN="$VENV/Scripts"; else BIN="$VENV/bin"; fi
PY="$BIN/python"
[ -x "$PY" ] || PY="$BIN/python.exe"
[ -x "$PY" ] || die "the virtualenv has no python: remove $VENV and try again."
ALEMBIC="$BIN/alembic"
[ -x "$ALEMBIC" ] || ALEMBIC="$BIN/alembic.exe"

# Git Bash hands out /c/... paths, and a Windows Python does not understand them. Everything the
# interpreter is given is therefore either relative to $ROOT (we are already there) or translated.
winpath() {
    if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

say "Backend and CLI package"
"$PY" -m pip install --quiet --upgrade pip wheel
"$PY" -m pip install --quiet -e "backend[dev]" -e "packages/autoskill-local[dev]"
echo "  autoskill + autoskill-local installed in editable mode"

# --- llmswitch: the only source of the LLM provider choice --------------------------------

say "Provider library (llmswitch)"
if [ -z "$LLMSWITCH" ] && [ -d "$ROOT/../llmswitch" ]; then
    LLMSWITCH="$(cd "$ROOT/../llmswitch" && pwd)"
    echo "  found next to the repository: $LLMSWITCH"
fi
if [ -n "$LLMSWITCH" ]; then
    if [ -d "$LLMSWITCH" ]; then
        "$PY" -m pip install --quiet -e "$(winpath "$LLMSWITCH")"
    else
        "$PY" -m pip install --quiet "$LLMSWITCH"
    fi
fi
if "$PY" -c 'import llmswitch' 2>/dev/null; then
    echo "  llmswitch $("$PY" -c 'import llmswitch; print(llmswitch.__version__)') installed"
else
    warn "llmswitch is not installed: AutoSkill will start, but no interview, draft or coach"
    warn "reply can run until it is. Re-run with --llmswitch <path-or-git-url>."
fi

# --- configuration -----------------------------------------------------------------------

say "Configuration (backend/.env)"
if [ -f "$ROOT/backend/.env" ]; then
    echo "  kept as it is"
else
    SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    sed "s|^AUTOSKILL_SECRET_KEY=.*|AUTOSKILL_SECRET_KEY=$SECRET|" "$ROOT/.env.example" > "$ROOT/backend/.env"
    echo "  written from .env.example, with a secret key of its own"
fi

say "Database schema"
(cd "$ROOT/backend" && "$ALEMBIC" upgrade head)

if [ "$SKIP_WHEEL" -eq 0 ]; then
    say "autoskill-local wheel (served at /dl/autoskill-local/latest)"
    mkdir -p "$ROOT/backend/data/dist"
    "$PY" -m pip wheel --quiet --no-deps -w backend/data/dist packages/autoskill-local
    echo "  built"
fi

# --- frontend ----------------------------------------------------------------------------

if [ "$SKIP_FRONTEND" -eq 0 ]; then
    say "Frontend"
    command -v npm >/dev/null 2>&1 || die "npm not found. Install Node 20+ and run this again."
    node_major="$(node -p 'process.versions.node.split(".")[0]')"
    [ "$node_major" -ge 20 ] || warn "Node $node_major is older than the 20 this project expects."
    # `npm ci` deletes node_modules before installing, and on Windows a .node binary a running
    # dev server has loaded cannot be unlinked - the run dies halfway, leaving a half-deleted
    # tree. A tree that is already there is updated in place instead.
    if [ "$CLEAN_FRONTEND" -eq 1 ] || [ ! -d "$ROOT/frontend/node_modules" ]; then
        NPM_COMMAND=ci
    else
        NPM_COMMAND=install
    fi
    if ! (cd "$ROOT/frontend" && npm "$NPM_COMMAND" --no-audit --no-fund); then
        warn "npm could not write into node_modules. A dev server holding those files is the"
        warn "usual reason: stop ./start.sh (or npm run dev) and run this again."
        exit 1
    fi
    echo "  dependencies installed (npm $NPM_COMMAND)"
fi

say "Done"
cat <<EOF
  Start everything with ./start.sh  (API on :8000, UI on :5173)

  The first account you register in the UI becomes the administrator. Then open
  Administration -> AI providers and configure the model: that panel is the only
  place the choice of provider comes from.
EOF
