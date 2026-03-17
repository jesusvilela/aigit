# AIGit

[![CI](https://github.com/jesusvilela/aigit/actions/workflows/ci.yml/badge.svg)](https://github.com/jesusvilela/aigit/actions/workflows/ci.yml)
[![Semantic Maintenance](https://github.com/jesusvilela/aigit/actions/workflows/semantic-maintenance.yml/badge.svg)](https://github.com/jesusvilela/aigit/actions/workflows/semantic-maintenance.yml)

AI-native semantic version control on top of Git.

AIGit keeps the Git object model untouched and layers a deterministic semantic graph on top so humans, agents, and CI can reason about intent instead of raw line diffs alone.

> Git remains the source of truth. AIGit adds semantic structure, lineage, provenance, and automation around it.

## Why AIGit

| Problem | AIGit primitive | Outcome |
| --- | --- | --- |
| Source diffs lose intent | deterministic semantic chunking | agents and reviewers can inspect meaning-level changes |
| Refactors break traceability | chunk identity + lineage edges | semantic continuity survives movement and reshaping |
| AI edits need auditability | provenance records and commit trailers | generated work can be reviewed and verified |
| CI sees syntax, not semantics | semantic diff + semantic merge outputs | review and merge flows get machine-readable intent |
| autonomous loops drift | DeerFlow harness + admin UI | operators can observe and steer long-running work |

## What Ships Today

| Area | Included |
| --- | --- |
| Semantic core | chunking for `.py`, `.md`, and fallback file chunks |
| Lineage | stable semantic IDs, `edges.jsonl`, `chunk_index.json` |
| Review tooling | semantic diff and semantic merge reports |
| Provenance | append-only provenance log and commit trailers |
| Agent API | local HTTP chunk API via `aigit serve-api` |
| Autonomous delivery | DeerFlow bootstrap, recovery flow, admin UI |
| CI/CD | semantic freshness checks and PR-based maintenance automation |

## At A Glance

| If you need to... | Start here |
| --- | --- |
| rebuild semantic state | `aigit chunk` |
| review intent between refs | `aigit semantic-diff --base <ref> --head <ref>` |
| inspect merge risk | `aigit semantic-merge --base <ref> --ours <ref> --theirs <ref>` |
| record AI authorship context | `aigit record-provenance ...` |
| run autonomous work with visibility | `aigit init-deerflow`, `./scripts/run_deerflow_epics.sh`, `aigit admin-ui` |

## Repository Contract

- no custom Git object types
- normal GitHub and GitLab workflows still work
- semantic outputs are committed under `.semantic/`
- if AIGit is absent, the repository still behaves like a normal Git repo

## Storage Layout

```text
.semantic/
  schema_version
  ruleset.yaml
  manifest.jsonl
  edges.jsonl
  chunk_index.json
  provenance.jsonl
  cache/              # local-only, gitignored
```

## Fast Start

```bash
python -m pip install -e .
aigit chunk
aigit semantic-diff --base main --head HEAD --output semantic_diff.md
aigit semantic-merge --base main --ours HEAD --theirs feature --output semantic_merge.json
aigit record-provenance --agent codex --model gpt-5.2-codex --prompt "chunk update"
aigit serve-api --host 127.0.0.1 --port 8765
```

## CLI Surface

| Command | Purpose |
| --- | --- |
| `aigit chunk` | rebuild deterministic semantic artifacts for the current snapshot |
| `aigit semantic-diff --base <ref> --head <ref> --output <file>` | generate a PR-ready semantic diff report |
| `aigit semantic-merge --base <ref> --ours <ref> --theirs <ref>` | detect semantic conflicts from a shared base |
| `aigit record-provenance --agent <name> --model <model> --prompt <text>` | append provenance metadata for `HEAD` |
| `aigit commit -m <msg> --agent ... --model ... --prompt ...` | create a commit with an AI provenance trailer |
| `aigit serve-api` | expose `/healthz` and `/chunks` over HTTP |
| `aigit deerflow-workspace-path --thread-id <id>` | show host and sandbox workspace mappings |
| `aigit deerflow-import-repo --thread-id <id>` | stage the repo into DeerFlow's thread workspace |
| `aigit deerflow-export-repo --thread-id <id>` | pull a staged thread workspace back into the repo |

## DeerFlow Operator Loop

AIGit can provision a local DeerFlow harness under `.deerflow/` so autonomous agent runs can keep producing reviewable semantic changes.

```bash
aigit init-deerflow
aigit launch-epics
aigit admin-ui
cp .deerflow/.env.example .deerflow/.env
./scripts/run_deerflow_epics.sh
```

### Runtime contract

- live development directory bind-mounted at `/workspaces/aigit`
- first-class thread mount at `/mnt/user-data`
- staged repo mount at `/mnt/user-data/workspace/repo`
- recovery entrypoint: `./scripts/recover_deerflow.sh`

### Thread workspace flow

```bash
aigit deerflow-import-repo --thread-id roadmap-epic-01
aigit deerflow-export-repo --thread-id roadmap-epic-01
```

### Admin observability UI

```bash
aigit admin-ui --host 127.0.0.1 --port 7860
```

The UI exposes:

- DeerFlow API and container health
- 10-epic queue readiness and objective status
- thread workspace visibility for imports and exports
- semantic chunk metrics and chunk-type distribution
- operator actions for queue rebuild, harness recovery, and semantic regeneration

### Default model catalog

- `GPT-4.1`
- `GPT-4o`
- `GPT-4o Mini`
- `GPT-4.1 Mini`
- `GPT-4.1 Nano`

### DeerFlow entrypoint

```text
http://localhost:2026/workspace/chats/new
```

## CI/CD Safety Rails

Two GitHub Actions workflows ship in `.github/workflows/`:

- `ci.yml` validates every push and pull request with tests, semantic rebuild, and stale-artifact enforcement
- `semantic-maintenance.yml` runs on demand or weekly, refreshes `.semantic/**`, and opens a pull request instead of pushing directly to `main`

Safety properties:

- no force-push or direct maintenance commit to `main`
- semantic maintenance is constrained to `.semantic/**`
- disposable caches are deleted before and after maintenance runs
- generated junk such as `__pycache__`, `.pyc`, and `aigit.egg-info/` is excluded from semantic indexing

## Release Status

### Cycle 1

The first release wave launched 10 active epics spanning deterministic chunking, lineage, semantic CI, merge UX, provenance, API hardening, DeerFlow delivery, language expansion, performance, and release governance.

Primary references:

- `docs/EPICS_ROADMAP.md`
- `docs/epics/EPIC-01-ruleset-engine-v2.md` through `docs/epics/EPIC-10-release-governance.md`

### Cycle 2: 10x release wave

The next 10x cycle is now staged as a follow-on charter focused on productizing the first wave into tighter release loops, stronger adoption rails, and more autonomous delivery.

- charter: `docs/CYCLE_02_10X_RELEASE.md`
- DeerFlow objective brief: `.deerflow/objectives/CYCLE-02-10X.md`

## Docs Index

- roadmap: `docs/EPICS_ROADMAP.md`
- cycle 2 charter: `docs/CYCLE_02_10X_RELEASE.md`
- MultiSOTA plans: `docs/MULTISOTA_CODEX.md`
- task checklist: `docs/MULTISOTA_CODEX_TASKS.md`
- release governance: `docs/RELEASE_GOVERNANCE.md`
- DeerFlow recovery playbook: `docs/DEERFLOW_RECOVERY.md`
- custom skill: `skills/custom/deerflow-aigit-autopilot/SKILL.md`

## Determinism Notes

- canonicalization uses LF normalization with trailing-whitespace trimming
- ruleset and schema version are committed for reproducible graph generation
- identity remaps stay conservative when similarity drops below threshold
- semantic artifacts are now filtered away from local cache and packaging noise so CI and local rebuilds stay byte-stable