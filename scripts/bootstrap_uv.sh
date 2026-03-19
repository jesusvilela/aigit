#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${HOME}/.local/bin/uv"
MODE="sync"

if [[ "${1:-}" == "--sync-only" ]]; then
  MODE="sync"
  shift
elif [[ "${1:-}" == "--up" ]]; then
  MODE="up"
  shift
fi

if [[ $# -gt 0 ]]; then
  echo "usage: ./scripts/bootstrap_uv.sh [--sync-only|--up]" >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if command -v uv >/dev/null 2>&1; then
  UV_CMD="$(command -v uv)"
else
  UV_CMD="${UV_BIN}"
fi

if [[ ! -x "${UV_CMD}" ]]; then
  echo "uv installation did not produce an executable binary" >&2
  exit 1
fi

cd "${REPO_ROOT}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-${REPO_ROOT}/.aigit/uv-cache}"
mkdir -p "${UV_CACHE_DIR}"

echo "Syncing AIGit with uv..."
echo "Using uv cache: ${UV_CACHE_DIR}"
"${UV_CMD}" sync --extra dev

if [[ "${MODE}" == "up" ]]; then
  echo "Launching AIGit stack with uv..."
  exec "${UV_CMD}" run aigit up
fi

echo "uv environment ready. Next steps:"
echo "  ${UV_CMD} run aigit up"
echo "  ${UV_CMD} run aigit improve"