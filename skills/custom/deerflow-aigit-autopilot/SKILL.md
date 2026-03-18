---
name: deerflow-aigit-autopilot
description: Configure and operate DeerFlow as an autonomous development harness for AIGit repositories, including setup, model/env configuration, Docker startup, and semantic CI loops. Use when Codex needs to initialize deer-flow, maintain long-running agent workflows, or ship iterative AIGit changes with semantic artifacts.
---

# DeerFlow AIGit Autopilot

Use this skill to run DeerFlow against an AIGit repository while preserving deterministic semantic artifacts.

## Execute bootstrap

1. Run `aigit init-deerflow` from the repository root.
2. Copy `.deerflow/.env.example` to `.deerflow/.env`.
3. Set model/search secrets in `.deerflow/.env`.
4. Start the harness with `./scripts/run_deerflow.sh`.

## Keep AIGit deterministic

1. Regenerate semantic artifacts after each meaningful change: `aigit chunk`.
2. Verify the CLI and tests before commit:
   - `pytest -q`
   - `aigit --help`
3. Commit source and semantic manifest files together.

## Run autonomous iteration loop

1. Create or pick a focused objective.
2. Let DeerFlow decompose and execute subtasks.
3. Pull produced edits back into this repository branch.
4. Re-run semantic generation and tests.
5. Commit in small increments with provenance metadata.

## Produce MultiSOTA Codex planning docs

Create or refresh:
- `docs/MULTISOTA_CODEX.md`
- `docs/MULTISOTA_CODEX_TASKS.md`

Use `references/multisota-codex-template.md` for structure and acceptance criteria.
