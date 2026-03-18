# AIGit Development Roadmap

This roadmap now tracks two linked waves:

- Cycle 1: the currently launched 10-epic foundation
- Cycle 2: a new 10x release wave that productizes and operationalizes the first cycle

## Execution Cadence

- **Sprint length:** 1 week
- **Review gate:** all epics must produce semantic outputs where applicable (`aigit chunk`, semantic diff/merge artifacts)
- **Definition of done:** tests pass, docs updated, no secrets in git, PR includes provenance context

## Cycle 1 Epic Portfolio

1. **EPIC-01 Deterministic Ruleset Engine v2** (`docs/epics/EPIC-01-ruleset-engine-v2.md`)
2. **EPIC-02 Chunk Identity & Lineage Hardening** (`docs/epics/EPIC-02-identity-lineage-hardening.md`)
3. **EPIC-03 Semantic Diff Quality & CI Integration** (`docs/epics/EPIC-03-semantic-diff-ci.md`)
4. **EPIC-04 Semantic Merge Conflict Resolution UX** (`docs/epics/EPIC-04-semantic-merge-ux.md`)
5. **EPIC-05 AI Provenance Audit Chain** (`docs/epics/EPIC-05-provenance-audit-chain.md`)
6. **EPIC-06 Agent API Stabilization** (`docs/epics/EPIC-06-agent-api-stabilization.md`)
7. **EPIC-07 DeerFlow Autonomous Delivery Pipeline** (`docs/epics/EPIC-07-deerflow-delivery-pipeline.md`)
8. **EPIC-08 Language Expansion Beyond Python/Markdown** (`docs/epics/EPIC-08-language-expansion.md`)
9. **EPIC-09 Performance & Scaling Baselines** (`docs/epics/EPIC-09-performance-scaling.md`)
10. **EPIC-10 Release Governance & Adoption Pack** (`docs/epics/EPIC-10-release-governance.md`)

## Cycle 1 Launch Status

| Epic | Owner Mode | Status | First Milestone |
|---|---|---|---|
| EPIC-01 | local Codex | launched | versioned ruleset schema + validation |
| EPIC-02 | local Codex | launched | confidence-aware identity remap tests |
| EPIC-03 | local Codex + CI | launched | semantic diff markdown attached in CI |
| EPIC-04 | local Codex | launched | conflict taxonomy + merge hints JSON |
| EPIC-05 | local Codex | launched | immutable provenance append + verification |
| EPIC-06 | local Codex | launched | `/chunks` filters + pagination contract |
| EPIC-07 | local Codex + DeerFlow | launched | objective template + autopilot loop |
| EPIC-08 | local Codex | launched | parser plugin contract + first extra language |
| EPIC-09 | local Codex | launched | benchmark harness + budget thresholds |
| EPIC-10 | local Codex | launched | release checklist + migration notes |

## Cycle 2: 10x Release Wave

Cycle 2 builds on the existing epics instead of replacing them. The objective is to turn the current platform into a faster, safer, more operator-friendly release engine.

| Track | Scope | Status | First milestone |
| --- | --- | --- | --- |
| C2-01 | ruleset policy packs | chartered | repo-class presets and compatibility contracts |
| C2-02 | lineage replay suite | chartered | deterministic regression fixture matrix |
| C2-03 | semantic PR publishing | chartered | PR-ready semantic summary generation |
| C2-04 | merge rehearsal mode | chartered | pre-merge semantic conflict preview |
| C2-05 | provenance verification | chartered | proof checks in CLI and CI |
| C2-06 | API consumer kits | chartered | stable examples for agents and dashboards |
| C2-07 | persistent DeerFlow crews | chartered | resumable objective state handoff |
| C2-08 | polyglot parser expansion | chartered | JSON, YAML, and TypeScript parser contract |
| C2-09 | performance budgets | chartered | benchmark caps and regression alarms |
| C2-10 | adoption rails | chartered | rollout scorecards and release templates |

Cycle 2 charter: `docs/CYCLE_02_10X_RELEASE.md`
