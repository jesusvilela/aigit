# EPIC-01: Deterministic Ruleset Engine v2

## Goal
Strengthen ruleset versioning and validation so chunk graph generation is reproducible across machines.

## Deliverables
- Formal ruleset schema document and validator.
- CLI preflight check before chunking.
- Regression suite for canonicalization edge cases.

## Acceptance
- Same snapshot + same ruleset => byte-identical `.semantic/manifest.jsonl`.
