# Cycle 2 10x Task Checklist

This checklist turns the Cycle 2 charter into independently shippable slices.

## Global gate

- [ ] keep Git-native compatibility intact
- [ ] run `pytest -q`
- [ ] run `python -m aigit.cli chunk --repo .`
- [ ] keep `.semantic/` current in the same commit
- [ ] update docs for any changed operator flow

## C2-01 Ruleset policy packs

- [ ] define policy-pack structure
- [ ] document supported repo classes
- [ ] add validation tests for policy resolution

## C2-02 Lineage replay suite

- [x] add curated refactor fixtures (seed corpus)
- [x] assert expected semantic ID continuity
- [x] expose regressions clearly in CI

## C2-03 Semantic PR publishing

- [ ] produce deterministic semantic review summaries
- [ ] make output suitable for PR comments or artifacts
- [ ] document integration points for CI

## C2-04 Merge rehearsal mode

- [ ] add a rehearsal command or report mode
- [ ] classify conflict types
- [ ] produce reviewer-readable output

## C2-05 Provenance verification

- [ ] add provenance verification command
- [ ] enforce proof checks in CI where appropriate
- [ ] document failure modes and recovery

## C2-06 API consumer kits

- [ ] add example consumers for agents or dashboards
- [ ] document stable request and response shapes
- [ ] verify compatibility expectations

## C2-07 Persistent DeerFlow crews

- [ ] define resumable objective state
- [ ] persist handoff metadata safely
- [ ] document recovery and replay path

## C2-08 Polyglot parser expansion

- [ ] add JSON parser support
- [ ] add YAML parser support
- [ ] add TypeScript parser support
- [ ] protect Python and Markdown behavior with regression tests

## C2-09 Performance budgets

- [ ] add benchmark fixtures
- [ ] define target budgets
- [ ] surface regressions clearly in automation

## C2-10 Adoption rails

- [ ] publish rollout templates
- [ ] add migration guidance
- [ ] add operator scorecard or readiness checklist
