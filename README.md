# AIGit

<p align="center">
  <img src="assets/brand/aigit-mark.png" width="168" alt="AIGit semantic graph mark">
</p>

[![CI](https://github.com/jesusvilela/aigit/actions/workflows/ci.yml/badge.svg)](https://github.com/jesusvilela/aigit/actions/workflows/ci.yml)
[![Semantic Maintenance](https://github.com/jesusvilela/aigit/actions/workflows/semantic-maintenance.yml/badge.svg)](https://github.com/jesusvilela/aigit/actions/workflows/semantic-maintenance.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-111111.svg)](LICENSE)
[![Merge driver: 0 stale in 450 replayed merges](https://img.shields.io/badge/merge%20driver-0%20stale%20%2F%20450%20replayed%20merges-2a78d6.svg)](docs/evals/results/2026-10-15-merge-driver/README.md)

> **Git for files. AIGit for intent.**

AI-native semantic version control. People, agents, and CI get one shared, deterministic answer to the question a line diff never answers: *what did this change mean?*

It stays out of your way while doing it. The semantic layer is committed beside your code, merges as cleanly as your code does, and disappears without a trace if you remove it.

**Alpha software.** The semantic core is usable today; parser coverage and workflow ergonomics are still moving. Bring it to a real repository, inspect the output, and help shape the contract.

<br>

```text
静けさ — clarity before automation
```

## Why this exists

Code is no longer changed only by people. Agents can move quickly, but a line diff alone cannot answer the questions a team actually has:

- What capability changed?
- Did this refactor preserve its identity?
- Which agent produced this change, from which prompt and model?
- Where is the real merge risk?

AIGit keeps Git exactly as it is and adds a committed semantic layer beside it. No custom object store. No platform lock-in. No magic state that only one tool can read.

| You need | AIGit gives you | So you can |
| --- | --- | --- |
| review beyond line movement | deterministic semantic chunks and diffs | see intent-level change in pull requests |
| maintain context through refactors | stable IDs and lineage edges | trace a concept as it moves or changes shape |
| use agents responsibly | append-only provenance and commit trailers | audit generated work without guessing |
| merge agent work with confidence | semantic merge reports | surface conflict risk before the merge button |
| automate without surrendering control | a local API, CI checks, and an optional operator UI | keep humans in the loop |

## Merges that don't fight you

A committed semantic layer has a classic failure mode: two branches change the code cleanly, and the generated files beside it collide anyway. At merge-queue volume, that is a conflict on almost every busy file, and a human resolving metadata nobody wrote by hand.

AIGit's merge driver treats `.semantic/` as what it is, a function of the source. It merges the artifacts file by file, and re-chunks any file both branches touched from the source Git actually merged. That covers `merge`, `rebase`, `cherry-pick`, `revert`, `stash` and the `merge-tree` that merge queues run.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/evals/results/2026-10-15-merge-driver/figures/headline-dark.svg">
  <img alt="0 stale merges across 450 replayed merges, rebases and cherry-picks. 0 needless .semantic/ conflicts, where Git's text merge stopped 120 times on the same changes. 32 of 32 corner cases handled." src="docs/evals/results/2026-10-15-merge-driver/figures/headline-light.svg" width="760">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/evals/results/2026-10-15-merge-driver/figures/replay-outcomes-dark.svg">
  <img alt="Replayed concurrent changes. With Git's text merge, 40 of 150 stop on .semantic/ alone in each of merge, rebase and cherry-pick. With the AIGit driver, none do; the 25 genuine source conflicts are unchanged, and no merge is stale." src="docs/evals/results/2026-10-15-merge-driver/figures/replay-outcomes-light.svg" width="760">
</picture>

- **Only real conflicts stop you.** In 150 replayed pairs of concurrent changes, Git's text merge stopped 40 times per operation on `.semantic/` alone. The driver stopped on none of them, and every genuine source conflict still surfaced.
- **Never silently wrong.** Every merge's artifacts were compared byte for byte with a fresh rebuild. None was stale. Where the driver cannot follow Git (octopus merges, artifacts already stale), it stops and asks for `aigit chunk` rather than guess.
- **It runs Git's own merge, not an imitation.** `git merge-file` and Git's ort strategy disagreed on 8 of 400 random merges, 2 of them silently. So the driver merges with ort itself.

Full method, raw data, the 32-scenario corner-case sweep and the threats to validity are in the [evaluation report](docs/evals/results/2026-10-15-merge-driver/README.md). Rerun it with `make merge-driver-eval`.

```bash
aigit install-merge-driver   # once per clone; .gitattributes already routes the artifacts
```

## The quiet architecture

```mermaid
flowchart LR
    G["Git repository<br/>source of truth"] --> C["aigit chunk<br/>deterministic parsing"]
    C --> S[".semantic/<br/>committed semantic layer"]
    S --> R["semantic diff & merge<br/>reviewable intent"]
    S --> P["provenance<br/>who / model / prompt"]
    S --> A["local API & CI<br/>people, agents, automation"]
```

The contract is intentionally small:

- Git remains the source of truth.
- Semantic outputs live in `.semantic/` and can be committed, reviewed, and regenerated.
- Normal GitHub and GitLab workflows continue to work.
- If AIGit is removed, the repository remains a normal Git repository.

## Start in three breaths

Prerequisite: Python 3.10+ and Git. `uv` is the preferred environment manager; `pip` works too.

```bash
git clone https://github.com/jesusvilela/aigit.git
cd aigit
./scripts/bootstrap_uv.sh
uv run aigit chunk
uv run aigit install-merge-driver
```

Then ask a useful question of your repository:

```bash
# What changed in meaning between two refs?
uv run aigit semantic-diff --base main --head HEAD --output semantic_diff.md

# Where might two concurrent changes collide?
uv run aigit semantic-merge --base main --ours HEAD --theirs feature --output semantic_merge.json
```

<details>
<summary>Prefer pip?</summary>

```bash
python -m pip install -e ".[dev]"
aigit chunk
```

</details>

## A practical loop

```mermaid
sequenceDiagram
    participant D as Developer or agent
    participant G as Git
    participant S as AIGit semantic layer
    participant CI as CI / reviewer

    D->>G: edit and commit
    D->>S: aigit chunk
    S-->>G: commit .semantic artifacts
    D->>S: semantic-diff / semantic-merge
    S-->>CI: intent, lineage, and provenance
    CI-->>D: review with evidence
```

For AI-assisted commits, attach the work context as you create the commit:

```bash
aigit commit -m "refactor parser" \
  --agent codex \
  --model gpt-5.2-codex \
  --prompt "extract parser helpers while preserving behavior"
```

## What is ready now

| Surface | Available today |
| --- | --- |
| Semantic core | deterministic chunking for Python, Markdown, JSON, YAML, TypeScript, and a safe file fallback |
| Identity and lineage | stable semantic IDs, conservative lineage edges, `chunk_index.json` |
| Review tooling | semantic diff and semantic merge reports |
| Merging | a Git merge driver that merges `.semantic/` by source file, and a workflow that unblocks the hosted merge button |
| Provenance | append-only provenance log, signed records, commit trailers |
| Agent access | local HTTP API through `aigit serve-api` |
| Team automation | semantic freshness checks and PR-based maintenance workflow |
| Operator mode | optional DeerFlow harness and Gradio admin UI |

## Command map

| Command | Use it when |
| --- | --- |
| `aigit chunk` | you need to rebuild semantic state |
| `aigit validate-ruleset` | you need to confirm the committed parser contract is valid |
| `aigit eval-lineage --fixtures <file>` | you need reproducible lineage precision and recall evidence |
| `aigit semantic-diff --base <ref> --head <ref>` | you want an intent-focused comparison |
| `aigit semantic-merge --base <ref> --ours <ref> --theirs <ref>` | you need early merge-risk signals |
| `aigit record-provenance --agent … --model … --prompt …` | you need an auditable record of AI context |
| `aigit commit -m <message> --agent … --model … --prompt …` | you want provenance attached to a commit |
| `aigit install-merge-driver` | concurrent branches keep colliding on `.semantic/` files |
| `aigit serve-api` | an agent or tool needs semantic context locally |
| `aigit improve` | you want a concise local chunk-and-test cycle |
| `aigit subagent-scout` | you need a quick repository diagnosis |
| `aigit up` | you are running the optional DeerFlow operator stack |

Run `aigit --help` for the full command reference.

## Install profiles

| Install | Includes |
| --- | --- |
| `pip install aigit` | pure-stdlib semantic core, diff/merge, provenance, and local API |
| `pip install "aigit[ui]"` | the Gradio observability UI (`aigit admin-ui`) |
| `pip install "aigit[dev]"` | test dependencies |
| `aigit[deerflow]` + Docker | optional DeerFlow harness; requires a DeerFlow checkout at runtime |

## The committed layer

```text
.semantic/
  schema_version       # reproducibility contract
  ruleset.yaml         # parser and ruleset settings
  manifest.jsonl       # semantic chunks
  edges.jsonl          # identity and lineage links
  chunk_index.json     # fast lookup
  provenance.jsonl     # append-only AI work record
  cache/                # local-only, ignored by Git
```

`manifest.jsonl` and `chunk_index.json` are never merged line by line: the driver merges them per source file and re-chunks files both branches changed. `edges.jsonl` and `provenance.jsonl` hold immutable records and merge as sets, so two branches recording provenance never collide at the end of the file. Every chunk carries its file's hash. Given fresh artifacts on both sides, even a plain text merge, such as a hosted merge button or a clone without the driver, either conflicts or produces exactly what `aigit chunk` would. When a pull request conflicts with its base only in `.semantic/`, the Semantic Merge workflow merges the base in with the driver and pushes. What no merge can fix (artifacts that were already stale, a branch that predates AIGit) is what `aigit chunk --check` in CI is for. Details and limits are in the [evaluation report](docs/evals/results/2026-10-15-merge-driver/README.md).

## Community: build the contract with us

This project needs skeptical builders: people who review AI-generated changes, maintain developer tools, build coding agents, or care about durable software history.

Good first contributions are deliberately small:

1. Try `aigit chunk` on a repository you know well.
2. Open an issue with a confusing chunk, missed lineage link, or workflow friction.
3. Pick a documented roadmap item, parser improvement, test, or documentation fix.
4. Send a focused pull request.

Please read [Contributing](CONTRIBUTING.md), our [Code of Conduct](CODE_OF_CONDUCT.md), and [Security policy](SECURITY.md) before participating. We are especially interested in real-world examples where semantic context would make review safer or faster.

## For maintainers and operators

The optional DeerFlow stack is for long-running autonomous delivery with visibility and recovery controls. It is not required for the semantic core.

```bash
cp .deerflow/.env.example .deerflow/.env
aigit up
aigit admin-ui --host 127.0.0.1 --port 7860
```

Useful references:

- [Beta readiness and release artifacts](docs/BETA_READINESS.md)
- [Development journal](docs/DEVELOPMENT_JOURNAL.md)
- [Evaluation program](docs/evals/README.md)
- [Merge driver evaluation](docs/evals/results/2026-10-15-merge-driver/README.md)
- [Changelog](CHANGELOG.md)
- [Release governance](docs/RELEASE_GOVERNANCE.md)
- [Roadmap](docs/EPICS_ROADMAP.md)
- [DeerFlow recovery playbook](docs/DEERFLOW_RECOVERY.md)
- [Cycle 2 release charter](docs/CYCLE_02_10X_RELEASE.md)
- [Custom DeerFlow autopilot skill](skills/custom/deerflow-aigit-autopilot/SKILL.md)

## Verify a checkout

```bash
uv sync --extra dev
pytest -q
./scripts/ci_refresh_semantics.sh
git diff --exit-code -- .semantic
```

The CI matrix tests Python 3.10–3.12, validates the lockfile, and rejects stale committed semantic artifacts.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Brand

The AIGit mark and its usage guidance live in [Brand guidelines](docs/BRAND.md). The transparent PNG is ready for social posts, presentations, and repository use.
