#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUEUE_FILE="$REPO_ROOT/.deerflow/epic_queue.json"
OBJECTIVES_DIR="$REPO_ROOT/.deerflow/objectives"
"$REPO_ROOT/scripts/run_deerflow.sh"
if [ ! -f "$QUEUE_FILE" ]; then
  echo "epic queue missing. Run: aigit launch-epics" >&2
  exit 1
fi
echo "DeerFlow harness is running for the roadmap."
echo "Workspace UI: http://localhost:2026/workspace/chats/new"
echo "Root URL http://localhost:2026 is the generic DeerFlow landing page."
echo "Load the master objective: $OBJECTIVES_DIR/ALL_EPICS.md"
echo "Per-epic objective files are in: $OBJECTIVES_DIR"
echo "Queue manifest: $QUEUE_FILE"
echo "Direct AIO sandbox contract: /mnt/user-data is the mounted thread root."
echo "Live development directory mount: /workspaces/aigit"
echo "Stage a repo mirror with: aigit deerflow-import-repo --thread-id <thread-id>"
echo "Prefer DeerFlow work in: /workspaces/aigit"
echo "Tell DeerFlow to work in: /mnt/user-data/workspace/repo"
echo "Pull thread changes back with: aigit deerflow-export-repo --thread-id <thread-id>"
echo "If the harness loses context or returns sandbox-path nonsense, run: $REPO_ROOT/scripts/recover_deerflow.sh"
