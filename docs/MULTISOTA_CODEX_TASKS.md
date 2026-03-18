# MultiSOTA Codex Task Checklist

## Bootstrap

- [ ] Run `python -m pip install -e .`
- [ ] Run `aigit init-deerflow`
- [ ] Copy `.deerflow/.env.example` to `.deerflow/.env`
- [ ] Add required API keys in `.deerflow/.env`
- [ ] Start DeerFlow with `./scripts/run_deerflow_epics.sh`
- [ ] Verify `curl -sS http://localhost:2026/api/models` succeeds
- [ ] Avoid raw `docker compose` unless `DEER_FLOW_ROOT` is exported first
- [ ] For repo-editing threads, run `aigit deerflow-import-repo --thread-id <id>` before asking DeerFlow to modify code
- [ ] Keep the working repo path inside DeerFlow at `/mnt/user-data/workspace/repo`

## Per-objective loop

- [ ] Define objective and acceptance criteria
- [ ] Execute DeerFlow task sequence
- [ ] If DeerFlow loses repo context or returns bad sandbox-only paths, run `./scripts/recover_deerflow.sh`
- [ ] Export thread workspace changes with `aigit deerflow-export-repo --thread-id <id>`
- [ ] Run `pytest -q`
- [ ] Run `aigit chunk`
- [ ] (Optional) Run semantic report command:
      `aigit semantic-diff --base main --head HEAD --output semantic_diff.md`
- [ ] Commit source + semantic artifacts together

## PR quality gate

- [ ] README/docs updated if behavior changed
- [ ] No secrets committed
- [ ] Semantic artifacts present and current
- [ ] Commit message and PR body include provenance context
