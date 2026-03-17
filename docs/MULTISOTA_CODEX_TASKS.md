# MultiSOTA Codex Task Checklist

## Bootstrap

- [ ] Run `python -m pip install -e .`
- [ ] Run `aigit init-deerflow`
- [ ] Copy `.deerflow/.env.example` to `.deerflow/.env`
- [ ] Add required API keys in `.deerflow/.env`
- [ ] Start DeerFlow with `./scripts/run_deerflow.sh`

## Per-objective loop

- [ ] Define objective and acceptance criteria
- [ ] Execute DeerFlow task sequence
- [ ] Apply produced changes locally
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
