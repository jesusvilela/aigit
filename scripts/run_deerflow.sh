#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEERFLOW_DIR="$REPO_ROOT/.deerflow/vendor/deer-flow"
if [ ! -d "$DEERFLOW_DIR" ]; then
  echo "deer-flow vendor directory missing. Run: aigit init-deerflow" >&2
  exit 1
fi
cd "$DEERFLOW_DIR"
make docker-init
make docker-start
