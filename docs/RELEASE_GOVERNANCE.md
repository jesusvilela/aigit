# Release Governance and Gradual Adoption Guide

This guide turns EPIC-10 into a practical release policy for AIGit. The goal is to keep releases predictable for Git-native teams while preserving deterministic semantic artifacts.

## Release Checklist

Before tagging a release candidate:

- Run `pytest -q` from the repository root.
- Rebuild semantic artifacts with `python -m aigit.cli chunk --repo /workspaces/aigit` or `aigit chunk`.
- If `.semantic/ruleset.yaml` or ruleset-related parsing logic changed, run `python -m aigit.cli validate-ruleset`.
- Review the generated `.semantic/manifest.jsonl`, `.semantic/chunk_index.json`, and `.semantic/edges.jsonl` diffs as release artifacts, not incidental byproducts.
- Update [README.md](/workspaces/aigit/README.md) and any affected docs when CLI behavior, DeerFlow workflow, or release expectations change.
- Confirm `.deerflow/.env`, local caches, and vendored runtime state are not part of the release diff.

Ship the release only after the semantic output matches the expected behavior for the current snapshot and ruleset.

## Semantic Compatibility Criteria

Treat semantic compatibility as a first-class release gate:

- The same repository snapshot plus the same ruleset should produce byte-identical semantic manifests.
- Chunk identity changes should be intentional and explained in release notes when parser or canonicalization logic changes.
- Lineage regressions, missing chunks, or unexplained manifest churn should block the release until reviewed.

## Gradual Adoption Path

Teams do not need to adopt every AIGit feature on day one.

### Phase 1: Generate Artifacts Locally

- Run `aigit chunk` in an existing Git repository.
- Commit `.semantic/` outputs alongside source changes.
- Keep Git as the source of truth; AIGit adds metadata without replacing normal Git workflows.

### Phase 2: Add Review Signals

- Use `aigit semantic-diff` in pull requests to surface semantic changes for reviewers.
- Introduce provenance recording on AI-assisted changes with `aigit record-provenance` or `aigit commit`.

### Phase 3: Enforce Team Policy

- Gate merges on semantic validation and project tests.
- Standardize ruleset review so parser or chunking changes are approved intentionally.
- Use DeerFlow automation only after import/export and recovery steps are part of the team playbook.

## Version Bump Governance

Use version bumps to communicate what kind of migration teams should expect.

### When To Bump `schema_version`

Bump `.semantic/schema_version` when the serialized contract changes, for example:

- required manifest fields change
- output structure changes in a backward-incompatible way
- downstream tooling must be updated to read new artifacts

Schema bumps should be accompanied by migration notes and explicit compatibility guidance.

### When To Change the Ruleset

Change the ruleset when parsing or canonicalization behavior changes but the storage contract stays the same, for example:

- parser selection changes
- canonicalization rules change
- chunk boundary logic changes

Ruleset changes should include:

- a documented reason for the change
- regenerated semantic artifacts
- a note about expected chunk identity or lineage churn

## Release Notes Expectations

Every release should briefly state:

- whether schema compatibility changed
- whether ruleset behavior changed
- whether downstream teams need to regenerate semantic artifacts
- whether DeerFlow workflow or recovery guidance changed

That keeps adoption incremental and avoids surprising teams that are using AIGit in otherwise standard Git repositories.
