# DeerFlow Recovery Playbook

## When to use this

Use the recovery flow if any of these happen:

- `http://localhost:2026/api/models` or `http://localhost:2026/api/langgraph/openapi.json` starts failing.
- DeerFlow claims success from `/mnt/user-data/workspace` but the repository working tree does not reflect the change.
- Containers were restarted manually with raw `docker compose` and thread workspace mounts look wrong.

## Normal startup

```bash
./scripts/run_deerflow_epics.sh
```

This wrapper syncs the local DeerFlow config into the vendored harness and starts the roadmap stack with the expected objective bundle. The live development checkout is bind-mounted at `/workspaces/aigit`, and the direct AIO sandbox contract remains `/mnt/user-data` for thread state and `/mnt/user-data/workspace/repo` for the staged checkout.

## One-command recovery

```bash
./scripts/recover_deerflow.sh
```

The recovery script:

- re-syncs `.deerflow/config.yaml` and `.deerflow/.env` into `.deerflow/vendor/deer-flow/`
- exports `DEER_FLOW_ROOT` so Docker mounts the correct host-side thread workspace paths
- restarts the DeerFlow development stack
- waits for `/api/models` and `/api/langgraph/openapi.json` to become healthy again

## Important guardrail

Prefer the wrapper scripts over raw `docker compose` commands. If you bypass them, export the vendored DeerFlow root first:

```bash
export DEER_FLOW_ROOT=/absolute/path/to/.deerflow/vendor/deer-flow
```

Without that variable, DeerFlow can restart with incorrect host-mount paths and sandbox runs may complete against the wrong workspace.

## After recovery

1. Reload `.deerflow/objectives/ALL_EPICS.md`.
2. Prefer the live checkout at `/workspaces/aigit` for direct edits.
3. For isolated edit-heavy work, stage the checkout into the thread sandbox with `aigit deerflow-import-repo --thread-id <id>` and tell DeerFlow to work inside `/mnt/user-data/workspace/repo` while treating `/mnt/user-data` as the mounted thread root.
4. Export validated changes back with `aigit deerflow-export-repo --thread-id <id>`, then run `pytest -q` and `python -m aigit.cli chunk --repo /workspaces/aigit`.
