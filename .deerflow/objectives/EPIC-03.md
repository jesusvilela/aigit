# DeerFlow Objective: EPIC-03: Semantic Diff Quality & CI Integration

Source epic: docs/epics/EPIC-03-semantic-diff-ci.md

## Goal
Make semantic diff a first-class PR artifact.

## Deliverables
- CI job template to run `aigit semantic-diff`.
- Human-friendly summary formatting and section grouping.
- Fallback behavior when manifests are missing on base branch.

## Acceptance
- Every PR can include a deterministic semantic diff report.

## Execution Guardrails
- Work only within this repository checkout.
- Prefer the live development directory `/workspaces/aigit` when it is mounted in the sandbox.
- When a staged repo mirror exists, use `/mnt/user-data/workspace/repo` as the writable checkout for import/export.
- Preserve deterministic semantic outputs under `.semantic/`.
- Regenerate semantic artifacts after meaningful changes with `aigit chunk`.
- Run `pytest -q` before handing work back.
- Update README/docs when user-facing behavior changes.
- Do not commit secrets or vendor-state changes unintentionally.

## Delivery Loop
1. Restate the epic objective and identify the smallest reviewable slice.
2. Implement the slice with tests first when practical.
3. Run validation commands and capture failures precisely.
4. Regenerate semantic artifacts and summarize the diff.
5. Stop with a review-ready change summary, risks, and next slice.
