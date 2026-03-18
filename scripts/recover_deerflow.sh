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
make docker-stop || true
make docker-start
docker restart deer-flow-nginx >/dev/null 2>&1 || true

for endpoint in "http://localhost:2026/api/models" "http://localhost:2026/api/langgraph/openapi.json"; do
  ready=0
  for _ in $(seq 1 20); do
    if curl -fsS "$endpoint" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "DeerFlow recovered but did not pass health check: $endpoint" >&2
    exit 1
  fi
done

echo "DeerFlow recovery complete."
echo "Workspace UI: http://localhost:2026/workspace/chats/new"
echo "Live development directory mount: /workspaces/aigit"
echo "Reload the master objective: $REPO_ROOT/.deerflow/objectives/ALL_EPICS.md"
