#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEERFLOW_DIR="$REPO_ROOT/.deerflow/vendor/deer-flow"
RUNTIME_HOME="$DEERFLOW_DIR/backend/.deer-flow"
LOCAL_CONFIG="$REPO_ROOT/.deerflow/config.yaml"
LOCAL_ENV="$REPO_ROOT/.deerflow/.env"
LOCAL_ENV_EXAMPLE="$REPO_ROOT/.deerflow/.env.example"
LOCAL_AGENTS_DIR="$REPO_ROOT/.deerflow/agents"
LOCAL_USER_PROFILE="$REPO_ROOT/.deerflow/USER.md"

ensure_env_defaults() {
  local env_file="$1"
  local example_file="$2"
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^# || "$line" != *=* ]] && continue
    local key="${line%%=*}"
    if ! grep -q "^${key}=" "$env_file" 2>/dev/null; then
      printf '%s=\n' "$key" >> "$env_file"
    fi
  done < "$example_file"
}

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
if [ -f "$DEERFLOW_DIR/.env" ] && [ -f "$LOCAL_ENV_EXAMPLE" ]; then
  ensure_env_defaults "$DEERFLOW_DIR/.env" "$LOCAL_ENV_EXAMPLE"
fi
mkdir -p "$RUNTIME_HOME/agents"
if [ -f "$LOCAL_USER_PROFILE" ]; then
  cp "$LOCAL_USER_PROFILE" "$RUNTIME_HOME/USER.md"
fi
if [ -d "$LOCAL_AGENTS_DIR" ]; then
  for agent_dir in "$LOCAL_AGENTS_DIR"/*; do
    [ -d "$agent_dir" ] || continue
    target_dir="$RUNTIME_HOME/agents/$(basename "$agent_dir")"
    mkdir -p "$target_dir"
    [ -f "$agent_dir/config.yaml" ] && cp "$agent_dir/config.yaml" "$target_dir/config.yaml"
    [ -f "$agent_dir/SOUL.md" ] && cp "$agent_dir/SOUL.md" "$target_dir/SOUL.md"
  done
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
