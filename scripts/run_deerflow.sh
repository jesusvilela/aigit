#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEERFLOW_DIR="$REPO_ROOT/.deerflow/vendor/deer-flow"
LOCAL_CONFIG="$REPO_ROOT/.deerflow/config.yaml"
LOCAL_ENV="$REPO_ROOT/.deerflow/.env"
LOCAL_ENV_EXAMPLE="$REPO_ROOT/.deerflow/.env.example"
if [ ! -d "$DEERFLOW_DIR" ]; then
  echo "deer-flow vendor directory missing. Run: aigit init-deerflow" >&2
  exit 1
fi
cd "$DEERFLOW_DIR"
make docker-init
make docker-start
if [ -f "$LOCAL_CONFIG" ]; then
  cp "$LOCAL_CONFIG" "$DEERFLOW_DIR/config.yaml"
fi
if [ -f "$LOCAL_ENV" ]; then
  cp "$LOCAL_ENV" "$DEERFLOW_DIR/.env"
elif [ -f "$LOCAL_ENV_EXAMPLE" ] && [ ! -f "$DEERFLOW_DIR/.env" ]; then
  cp "$LOCAL_ENV_EXAMPLE" "$DEERFLOW_DIR/.env"
fi
export DEER_FLOW_ROOT="$DEERFLOW_DIR"
cd "$DEERFLOW_DIR"
make docker-init
make docker-start
docker restart deer-flow-nginx >/dev/null 2>&1 || true
