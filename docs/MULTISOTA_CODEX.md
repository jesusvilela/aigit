# MultiSOTA Codex Strategy for AIGit

## Objective

Operate AIGit with an autonomous DeerFlow harness while preserving deterministic semantic history and Git-host compatibility.

## Why this stack

AIGit contributes stable semantic chunk identity, semantic diffs, and semantic merge insights.
DeerFlow contributes parallelized agent execution, long-running task decomposition, and sandboxed delivery.

Together they provide a multi-SOTA path:
- state-of-the-art semantic version control ergonomics for AI workflows
- state-of-the-art autonomous execution harness for coding/research loops

## Operating model

1. Bootstrap DeerFlow with `aigit init-deerflow`.
2. Execute iterative tasks via DeerFlow.
3. Pull changes into branch and regenerate semantic graph (`aigit chunk`).
4. Validate via tests and semantic reports.
5. Commit and open PR with semantic context.

## Guardrails

- Git remains the source of truth.
- `.semantic/` files are versioned and deterministic.
- Unknown identity mappings default to new semantic node.
- Local-only secrets and vendor directories remain ignored.

## KPI targets

- Reduced review ambiguity: semantic diff in each PR.
- Reduced merge risk: semantic conflict report for risky branches.
- Improved autonomy throughput: repeatable objective-to-commit loops.
