# EPIC-03: Semantic Diff Quality & CI Integration

## Goal
Make semantic diff a first-class PR artifact.

## Deliverables
- CI job template to run `aigit semantic-diff`.
- Human-friendly summary formatting and section grouping.
- Fallback behavior when manifests are missing on base branch.

## Acceptance
- Every PR can include a deterministic semantic diff report.
