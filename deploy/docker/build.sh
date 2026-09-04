#!/usr/bin/env bash
# Build the two AutoSkill images and hand them to k3s.
#
# k3s runs containerd, not docker, so an image built here is invisible to the cluster until it is
# imported. `docker save | ctr images import` is the shortest honest path; a registry would be the
# other one, and this cluster has none.
#
#   ./deploy/docker/build.sh                        llmswitch from ../llmswitch
#   ./deploy/docker/build.sh --llmswitch /opt/llmswitch
#   ./deploy/docker/build.sh --tag 2026-09-04       something other than :latest
#   ./deploy/docker/build.sh --no-import            build only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LLMSWITCH="${LLMSWITCH:-$ROOT/../llmswitch}"
TAG="${TAG:-latest}"
IMPORT=1

while [ $# -gt 0 ]; do
    case "$1" in
        --llmswitch) LLMSWITCH="$2"; shift 2 ;;
        --tag) TAG="$2"; shift 2 ;;
        --no-import) IMPORT=0; shift ;;
        -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31m  x %s\033[0m\n' "$*" >&2; exit 1; }

[ -d "$LLMSWITCH" ] || die "llmswitch not found at $LLMSWITCH - pass --llmswitch <path>"

# A build context of its own: the backend image needs llmswitch inside it, and llmswitch lives
# outside this repository.
CONTEXT="$(mktemp -d)"
trap 'rm -rf "$CONTEXT"' EXIT
say "Assembling the build context in $CONTEXT"
tar -C "$ROOT" \
    --exclude='.git' --exclude='node_modules' --exclude='.venv' --exclude='dist' \
    --exclude='__pycache__' --exclude='data' \
    -cf - backend packages frontend deploy | tar -C "$CONTEXT" -xf -
tar -C "$LLMSWITCH" --exclude='.git' --exclude='__pycache__' --exclude='*.egg-info' \
    -cf - . | (mkdir -p "$CONTEXT/llmswitch" && tar -C "$CONTEXT/llmswitch" -xf -)
echo "  backend, packages, frontend, deploy, llmswitch"

say "Building autoskill/api:$TAG"
docker build -f "$CONTEXT/deploy/docker/backend.Dockerfile" -t "autoskill/api:$TAG" "$CONTEXT"

say "Building autoskill/web:$TAG"
docker build -f "$CONTEXT/deploy/docker/web.Dockerfile" -t "autoskill/web:$TAG" "$CONTEXT"

if [ "$IMPORT" -eq 1 ]; then
    # A node running both docker and k3s has two containerd instances, each with a k8s.io
    # namespace of its own on a socket of its own. Only k3s's is the one the kubelet asks: a plain
    # `ctr` imports into docker's, where the image exists and the cluster still cannot see it.
    if command -v k3s >/dev/null 2>&1; then
        CTR="k3s ctr"
    elif command -v ctr >/dev/null 2>&1; then
        CTR="ctr"
    else
        die "neither k3s nor ctr found: run with --no-import, or import the images yourself"
    fi
    for image in "autoskill/api:$TAG" "autoskill/web:$TAG"; do
        say "Importing $image into containerd"
        docker save "docker.io/$image" | $CTR -n k8s.io images import -
    done
fi

say "Done"
echo "  autoskill/api:$TAG and autoskill/web:$TAG are ready"
