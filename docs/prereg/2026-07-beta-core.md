# Preregistration: beta-core semantic reliability

**Status:** proposed

**Locked on:** pending design-partner fixture selection

**Owner:** AIGit maintainers
**AIGit commit / ruleset:** to be recorded when locked

## Claim under test

For the supported language set, AIGit produces deterministic semantic artifacts and preserves the intended semantic identity through the preregistered refactor scenarios.

## Why this matters

Beta users need to know whether a semantic diff and lineage edge are stable enough to review. Without that, AIGit is only a visualization, not an engineering control.

## Scope and sampling

- **Population:** versioned fixtures representing Python, Markdown, JSON, YAML, and TypeScript changes.
- **Inclusion:** additions, deletions, moves, renames, extraction, inline refactors, and formatting-only changes that a maintainer can label unambiguously.
- **Exclusion:** generated code, binary files, malformed source, and transformations whose intended identity cannot be explained before observing output.
- **Target sample:** at least 20 labeled scenarios per supported parser family before beta promotion.
- **Baseline:** plain path-and-line matching for identity continuity; repeated clean AIGit rebuilds for determinism.

## Primary outcomes

1. **Determinism:** 100% byte-identical `.semantic/` output across three clean rebuilds of every fixture.
2. **Lineage precision:** at least 0.95 on the preregistered refactor scenarios.
3. **Lineage recall:** at least 0.90 on the preregistered refactor scenarios.

Any parser family below a threshold is explicitly excluded from beta claims until it is corrected and reevaluated.

## Method

Fixtures, their expected chunk identities, and expected lineage relations will be committed before the decisive run. A separate reviewer labels expected outcomes without access to the generated report when practical. Commands, Python version, OS, AIGit commit, ruleset, and raw manifests are retained with the results.

## Analysis plan

Compute precision as correct reported lineage edges divided by reported lineage edges; compute recall as correct reported lineage edges divided by expected lineage edges. Report every parser family separately and never substitute a pooled score for a failing family.

## Stop rules and deviations

The run ends once every preregistered fixture is evaluated three times in a clean environment. New scenarios discovered during work are logged as exploratory and held out of the decisive score unless this preregistration is amended before they are run.

## Outcome

The initial replay mechanism is executable through `aigit eval-lineage`. The checked-in corpus is a mechanism test, not the decisive beta run. Results from design-partner fixtures will be linked from `docs/evals/results/` and the development journal.
