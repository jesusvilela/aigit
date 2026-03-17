# MultiSOTA Codex Template

## Goal

State the specific product or engineering objective and the measurable success criteria.

## Baselines and SOTA comparison set

List at least three alternatives to compare (frameworks, workflows, or model/provider stacks).

| Option | Why it matters | Risks | Evidence source |
|---|---|---|---|
| AIGit + DeerFlow | Native semantic graph + autonomous harness | Setup complexity | repo tests/docs |
| DeerFlow only | Fast harness iteration | weaker semantic lineage | deer-flow docs |
| Plain Git + scripts | Lowest complexity | no semantic merge layer | internal baseline |

## Architecture decision

- Storage substrate: Git remains canonical.
- Semantic layer: `.semantic/` manifest and lineage files.
- Agent harness: DeerFlow local vendor and Docker runtime.
- Provenance: `aigit record-provenance` / trailer workflow.

## Implementation plan

1. Bootstrap harness and secrets.
2. Run first autonomous objective.
3. Validate semantic outputs and conflicts.
4. Publish semantic diff report for PR review.

## Acceptance checks

- `pytest -q` passes.
- `aigit chunk` updates deterministic artifacts.
- `aigit semantic-diff --base <ref> --head HEAD --output semantic_diff.md` succeeds.
- No secrets committed.

## Rollback plan

Describe how to disable DeerFlow while preserving normal Git workflows.
