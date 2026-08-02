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

## Forward journal: Cycle 2's next ten epics

These are prospective entries, not shipped claims. Each epic starts with a human question and names the evidence that must exist before aspiration becomes product truth.

### C2-01 — Rulesets that can explain themselves

**Question**

Can policy packs make semantic behavior legible across repository types without turning local judgment into invisible centralized control?

**Change**

Define small, versioned policy packs for common repository shapes, with compatibility boundaries and plain-language intent.

**Evidence**

Rebuild fixtures must remain byte-identical; maintainers must be able to predict a selected pack and explain every override.

**Decision**

Adopt only packs that reduce setup ambiguity without weakening repository autonomy. No silent policy inheritance.

**Open thread**

How should communities encode accessibility, safety, and regulatory needs without freezing one culture's assumptions into the default?

### C2-02 — Lineage with an honest memory

**Question**

Can AIGit remember identity through real refactors while admitting when continuity is uncertain?

**Change**

Expand the seed replay into preregistered, design-partner fixtures reported separately for every parser family.

**Evidence**

Three clean rebuilds per fixture, at least 20 labeled scenarios per family, precision of at least `0.95`, recall of at least `0.90`, and visible counterexamples.

**Decision**

Claim support parser by parser. A passing pooled score never conceals a failing language or repository shape.

**Open thread**

How should lineage represent collective authorship, generated code, and concepts that legitimately split or converge?

### C2-03 — Pull requests as shared understanding

**Question**

Do semantic summaries help reviewers decide better, or merely add confident-looking text to an already crowded interface?

**Change**

Publish deterministic, compact review artifacts that foreground changed capabilities, uncertainty, and provenance.

**Evidence**

Blinded reviewer tasks must measure decision accuracy, review time, and correction rate against ordinary diffs, including accessibility testing.

**Decision**

Ship summaries as evidence beside the diff, never as a substitute for source or accountable review.

**Open thread**

What is the quietest interface that still serves experts, newcomers, screen-reader users, and multilingual teams?

### C2-04 — Rehearsing conflict before impact

**Question**

Can teams see semantic collision early enough to negotiate intent rather than repair damage after integration?

**Change**

Create a non-destructive merge rehearsal that classifies risk, shows uncertainty, and offers reviewer-readable context.

**Evidence**

Evaluate calibration on historical merges: missed conflicts, false alarms, resolution usefulness, and time saved must all be reported.

**Decision**

Block nothing until signals are calibrated. High uncertainty invites conversation; it does not masquerade as certainty.

**Open thread**

How can rehearsals support asynchronous and globally distributed teams without rewarding whoever responds fastest?

### C2-05 — Provenance without surveillance

**Question**

Can AI-assisted work be accountable without creating a permanent ledger of unnecessary personal data?

**Change**

Verify provenance presence, integrity, scope, and redaction boundaries in the CLI and CI.

**Evidence**

Tamper, omission, replay, minimization, and recovery fixtures must fail safely while ordinary human-authored work remains possible.

**Decision**

Record what is needed to audit a change, not a worker. Reject designs that turn provenance into behavioral monitoring.

**Open thread**

Which facts should expire, remain local, or be disclosed only under an explicit governance process?

### C2-06 — An API that invites many kinds of builders

**Question**

Can agents, editors, civic tools, and small teams consume semantic context without bespoke integration or platform dependence?

**Change**

Publish stable consumer kits, bounded examples, compatibility guarantees, and machine-readable error contracts.

**Evidence**

Test reference consumers across supported versions, offline operation, pagination boundaries, degraded states, and assistive workflows.

**Decision**

Prefer a small durable protocol over an expanding catalog of privileged integrations.

**Open thread**

How do we keep entry costs low enough for independent developers and public-interest technology teams?

### C2-07 — Autonomous work that knows when to pause

**Question**

Can persistent agent crews resume useful work without erasing context, duplicating action, or displacing human authority?

**Change**

Add explicit state handoffs, bounded retries, interruption recovery, budgets, and visible stop reasons.

**Evidence**

Chaos exercises must cover restarts, stale objectives, unavailable services, conflicting instructions, and safe human takeover.

**Decision**

Resume only from inspectable committed state. When intent or authority is unclear, pause rather than improvise.

**Open thread**

What forms of consent and attribution should govern long-running collaboration between people and autonomous systems?

### C2-08 — Polyglot by design, not by extraction

**Question**

Can language expansion respect different programming traditions instead of forcing every codebase into a Python-shaped model?

**Change**

Harden JSON, YAML, and TypeScript contracts, then define a community parser interface with language-specific semantics.

**Evidence**

Publish per-language boundary, determinism, recovery, and lineage results, including non-English text and mixed-language repositories.

**Decision**

Call a language supported only when its own evidence passes. Fallback parsing stays explicit.

**Open thread**

How can maintainers of less-resourced languages shape the model and share stewardship rather than donate unpaid edge cases?

### C2-09 — Performance within earthly limits

**Question**

Can semantic review remain fast enough for daily work while making compute, energy, and storage costs visible?

**Change**

Establish repository-size budgets for latency, memory, artifact growth, incremental work, and avoidable recomputation.

**Evidence**

Reproducible benchmarks must report hardware context, warm and cold runs, variance, and energy proxies where trustworthy.

**Decision**

Optimize for useful work per resource, not throughput theatre. Regressions above a declared budget stop release.

**Open thread**

Which measurements are honest and portable enough to guide lower-carbon engineering without greenwashing?

### C2-10 — Adoption as a reversible choice

**Question**

Can a team try AIGit gradually, understand its obligations, and leave without losing history or agency?

**Change**

Publish tested rollout templates, readiness scorecards, migration paths, governance prompts, and clean removal instructions.

**Evidence**

Three non-trivial external repositories must complete adoption and recovery exercises, with friction and rejection reasons published.

**Decision**

Promote beta only when adoption is comprehensible, reversible, and supported by evidence beyond this repository.

**Open thread**

Who is excluded by the current installation, documentation, language, connectivity, or governance assumptions—and what will we change?
