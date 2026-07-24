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
| run a local improvement cycle | `aigit improve` |
| review intent between refs | `aigit semantic-diff --base <ref> --head <ref>` |
| inspect merge risk | `aigit semantic-merge --base <ref> --ours <ref> --theirs <ref>` |
| record AI authorship context | `aigit record-provenance ...` |
| bring up the full local stack | `aigit up` |
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

## Install & Extras

The semantic core is dependency-light. Heavy or optional surfaces are split
into extras so the core stays small for agents and CI:

| Install | Gets you |
| --- | --- |
| `pip install aigit` | semantic core: `chunk`, `semantic-diff`, `semantic-merge`, provenance, `serve-api` (pure stdlib) |
| `pip install "aigit[ui]"` | the Gradio admin observability UI (`aigit admin-ui`) |
| `pip install "aigit[dev]"` | test dependencies (`pytest`) |
| `aigit[deerflow]` + Docker | the DeerFlow autonomous harness (`aigit up`, `launch-epics`); requires a DeerFlow checkout and Docker at runtime |

## Fast Start

Preferred workflow with `uv`:

```bash
./scripts/bootstrap_uv.sh
uv run aigit up
uv run aigit improve
```

Pip-compatible fallback:

```bash
python -m pip install -e ".[dev]"
aigit up
aigit improve
aigit chunk
aigit semantic-diff --base main --head HEAD --output semantic_diff.md
aigit semantic-merge --base main --ours HEAD --theirs feature --output semantic_merge.json
aigit record-provenance --agent codex --model gpt-5.2-codex --prompt "chunk update"
```

## CLI Surface

| Command | Purpose |
| --- | --- |
| `aigit chunk` | rebuild deterministic semantic artifacts for the current snapshot |
| `aigit semantic-diff --base <ref> --head <ref> --output <file>` | generate a PR-ready semantic diff report |
| `aigit semantic-merge --base <ref> --ours <ref> --theirs <ref>` | detect semantic conflicts from a shared base |
| `aigit record-provenance --agent <name> --model <model> --prompt <text>` | append provenance metadata for `HEAD` |
| `aigit commit -m <msg> --agent ... --model ... --prompt ...` | create a commit with an AI provenance trailer |
| `aigit up` | recover DeerFlow and ensure the local chunk API and admin UI are running |
| `aigit improve [--test-path <path>]` | rebuild semantic artifacts and run the local test cycle with a concise summary |
| `aigit subagent-scout [--bootstrap-tool]` | scan the repo, emit a diagnosis report, and optionally scaffold `scripts/devx_quickcheck.sh` |
| `aigit subagent-scout [--bootstrap-tool]` | scan the repo, emit markdown + JSON diagnostics, and optionally scaffold `scripts/devx_quickcheck.sh` |
| `./scripts/bootstrap_uv.sh [--up]` | install `uv` if needed, sync the project with dev dependencies, and optionally launch the stack |
| `aigit serve-api` | expose `/healthz` and `/chunks` over HTTP |
| `aigit deerflow-workspace-path --thread-id <id>` | show host and sandbox workspace mappings |
| `aigit deerflow-import-repo --thread-id <id>` | stage the repo into DeerFlow's thread workspace |
| `aigit deerflow-export-repo --thread-id <id>` | pull a staged thread workspace back into the repo |

## Uv Workflow

`uv` is the preferred local environment manager for AIGit in Codespaces and other containerized environments. The project keeps standard `pyproject.toml` packaging, so `pip` still works, but `uv` gives faster syncs and keeps `aigit up` and `aigit improve` on the same interpreter and dependency graph.

Bootstrap the repo with one command:

```bash
./scripts/bootstrap_uv.sh
```

Bootstrap and launch the stack in one command:

```bash
./scripts/bootstrap_uv.sh --up
```

Equivalent manual flow:

```bash
uv sync --extra dev
uv run aigit up
uv run aigit improve
```

The checked-in `uv.lock` pins the resolved dependency graph for reproducible Codespaces and local setup.

The bootstrap script also defaults `UV_CACHE_DIR` to `.aigit/uv-cache` so `uv` stays writable inside restricted Codespaces containers.

## DeerFlow Operator Loop

AIGit can provision a local DeerFlow harness under `.deerflow/` so autonomous agent runs can keep producing reviewable semantic changes.

```bash
cp .deerflow/.env.example .deerflow/.env
aigit up
```

`aigit up` uses the current Python interpreter to launch local services in the background, which fits containerized environments such as Codespaces. When you start it with `uv run aigit up`, the background services stay on that same `uv`-managed interpreter and dependency graph.

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
- `semantic-maintenance.yml` runs on demand or weekly, executes `./scripts/ci_refresh_semantics.sh`, refreshes `.semantic/**`, and opens a pull request instead of pushing directly to `main`

In a clean checkout, local verification matches CI:

```bash
uv sync --extra dev
./scripts/ci_refresh_semantics.sh
git diff --exit-code -- .semantic
```

If you are not using `uv`, the equivalent fallback remains:

```bash
python -m pip install -e ".[dev]"
./scripts/ci_refresh_semantics.sh
git diff --exit-code -- .semantic
```

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

The next 10x cycle is chartered as a follow-on release wave focused on productizing the first wave into tighter release loops, stronger adoption rails, and more autonomous delivery. These tracks are roadmap commitments, not claims about the currently shipped parser surface.

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
