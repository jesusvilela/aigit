# DeerFlow Objective: AIGit Cycle 2 10x Release Wave

Source charter: docs/CYCLE_02_10X_RELEASE.md

## Objective

Drive the second release wave as a productization pass over the original 10-epic foundation.

Prioritize work that increases release confidence, semantic determinism, autonomous recovery, and adoption readiness without weakening Git-native compatibility.

## Success criteria

- semantic outputs stay deterministic in both local and CI rebuilds
- semantic review artifacts become easier to publish and consume in pull requests
- DeerFlow can resume interrupted release work with explicit state continuity
- adoption materials reduce operator guesswork during rollout

## Deliverables

- a working checklist for all ten Cycle 2 tracks
- implementation slices that can land independently without breaking `main`
- tests or fixtures for each new deterministic contract
- refreshed semantic artifacts and docs for every landed slice

## Recommended sequencing

1. provenance verification and performance budgets
2. ruleset policy packs and lineage replay fixtures
3. semantic PR publishing and merge rehearsal mode
4. API consumer kits and parser expansion
5. persistent DeerFlow crews and adoption rails

## Track breakdown

### C2-01 Ruleset policy packs

- define repo-class policy presets
- document compatibility guarantees
- add validation fixtures for policy resolution

### C2-02 Lineage replay suite

- add curated move and refactor fixtures
- capture expected semantic ID continuity
- block regressions in CI

### C2-03 Semantic PR publishing

- standardize semantic summary generation
- make the output suitable for PR posting or review notes
- keep it deterministic across local and CI runs

### C2-04 Merge rehearsal mode

- preview semantic conflicts before merge
- classify conflicts by type and severity
- emit reviewer-friendly output

### C2-05 Provenance verification

- verify provenance presence and integrity
- expose proof checks in CLI and CI
- fail safely when provenance is incomplete

### C2-06 API consumer kits

- add stable examples for agent and dashboard consumers
- document request and response expectations
- preserve backward compatibility for existing consumers

### C2-07 Persistent DeerFlow crews

- define resumable run-state handoff
- persist enough context to recover interrupted objectives
- keep recovery bounded and observable

### C2-08 Polyglot parser expansion

- add JSON, YAML, and TypeScript coverage
- preserve deterministic chunk IDs where possible
- ship tests that prove no regression in Python and Markdown parsing

### C2-09 Performance budgets

- create benchmark fixtures
- define baseline budgets and alarm thresholds
- keep budget checks cheap enough for CI

### C2-10 Adoption rails

- publish rollout templates and scorecards
- reduce bootstrap ambiguity for new teams
- tie docs to tested workflows, not aspirational flows

## Guardrails

- do not break normal Git workflows
- do not commit secrets
- commit docs, tests, and semantic artifacts together
- prefer PR-based automation over direct mutation of `main`

## Working reference

- charter: `docs/CYCLE_02_10X_RELEASE.md`
- checklist: `docs/CYCLE_02_10X_TASKS.md`