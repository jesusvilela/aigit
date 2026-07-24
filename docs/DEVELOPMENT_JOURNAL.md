# AIGit development journal

This is the public record of how AIGit earns confidence. It records decisions, evidence, reversals, and unresolved questions—not polished retrospective stories.

## How to use this journal

Add an entry when a change affects semantic identity, parser behavior, performance, provenance, or a public product claim. Keep entries short and link the underlying test, fixture, evaluation, preregistration, or release.

Each entry answers five things:

1. **Question** — what uncertainty are we reducing?
2. **Change** — what did we ship, test, or decide?
3. **Evidence** — what result supports the decision?
4. **Decision** — what follows, and what does not?
5. **Open thread** — what still needs to be learned?

## Entries

### 2026-07-24 — Public alpha baseline

**Question**

Can AIGit be used as a Git-native semantic layer without introducing opaque state or non-reproducible local behavior?

**Change**

Established the public alpha release surface: deterministic semantic artifacts, Python 3.10–3.12 CI, wheel smoke testing, community and security documentation, an initial brand system, and a release-evidence workflow.

**Evidence**

The repository’s test suite passes locally, semantic artifacts rebuild deterministically from the committed snapshot, and the built wheel exposes the CLI outside the checkout.

**Decision**

The project is ready for public-alpha design partners. It is not yet beta: parser-quality, lineage, usability, and performance claims need preregistered evaluations on representative repositories.

**Open thread**

Which repository shapes produce misleading chunks, weak lineage links, or review outputs that do not improve developer decisions? See the [evaluation program](evals/README.md) and [beta-core preregistration](prereg/2026-07-beta-core.md).

### 2026-07-24 — First lineage replay mechanism

**Question**

Can a labeled lineage claim be checked deterministically in the product and enforced in CI?

**Change**

Added `aigit eval-lineage`, a versioned seed corpus, and CI/release thresholds for lineage precision and recall. Added `aigit validate-ruleset` so the documented release contract is executable.

**Evidence**

The seed replay reports precision `1.000` and recall `1.000` across four deliberately small scenarios: move-and-rename, rename, small refactor, and unrelated change. See the [result note](evals/results/2026-07-24-lineage-replay-v1.md).

**Decision**

Keep the mechanism as a required regression gate. Do not interpret this result as beta evidence; the corpus is intentionally too small and has not yet been sourced from external repositories.

**Open thread**

Lock design-partner fixture selection, expand each parser family to the preregistered minimum, and report per-family—not pooled—precision and recall.
