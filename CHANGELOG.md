# Changelog

All notable changes to AIGit are documented here. The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `duplicate-work` also catches an addition that reimplements code already in
  the repository, reported with `scope: existing` (the earlier pass, now
  `scope: concurrent`, only saw two branches adding the same thing at once).
  Duplicating existing code needs no second agent, only one that did not know
  the codebase. A chunk the branch removed is skipped, so a rename is never
  reported as duplicating the name it replaced, and only an exact body match
  counts against existing code -- near-matching the whole corpus misfired on
  8.3% of additions when measured on this repo; requiring an exact body took
  that to 0%.
- `examples/crew_sim/`: a six-agent, six-timezone crew simulation that lands
  work through a trunk merge queue and asserts eight semantic-gate properties,
  including that a signed commit verifies and an unsigned one is rejected only
  once a signature is required.
  Deterministic by default (no network, no weights) so CI runs it; point it at
  any OpenAI-compatible API or local transformers checkpoint to drive it with a
  real model.
- Chunks carry a `body_fingerprint` (SimHash excluding the declaration line),
  so a rename no longer depresses its own similarity score.
- Public-alpha community, security, and brand materials.
- Release evidence automation: distributions, checksums, SPDX SBOM, and GitHub artifact attestations.
- `semantic-merge` detects `duplicate-work`: work both branches added under
  *different* names. `add/add` is keyed on the identifier, so two agents solving
  one ticket as `pick_provider` and `choose_provider` previously merged cleanly.
  Verbatim copies are always reported; near-matches are reported within a file
  and are advisory (see the precision note on `detect_duplicate_work`).
  `--no-duplicate-work` restricts the gate to name-keyed conflicts.

### Changed

- CI now smoke-tests the built wheel outside the source checkout.

### Fixed

- `duplicate-work` no longer reports two body-less chunks as identical. An
  empty body hashes to all zeros, and that value was treated as a fingerprint,
  so any two stubs spanning enough lines matched at 1.0. An absent body is now
  an absence of evidence and falls back to whole-chunk comparison.
- The incremental chunk cache is invalidated when the chunk schema changes.
  Cached entries are rehydrated with `Chunk(**record)`, so after a field is
  added a stale entry silently backfilled it with its default -- producing a
  manifest that differed from a clean rebuild and quietly degrading everything
  computed from that field.
- `duplicate-work` no longer misses pure renames. The identifier lives inside
  the hashed text, so scoring the whole chunk put a genuine name-only duplicate
  at 0.84 -- under the 0.85 gate. Matching on `body_fingerprint` scores that
  same pair 1.0, with no meaningful change in false pairs, and lineage replay
  still reports precision 1.0 / recall 1.0.
- Repeated anchors in one file no longer collide. A file defining `f` twice, or
  repeating a Markdown header, produced chunks sharing one semantic id, and
  every id-keyed consumer (`chunk_index.json`, `semantic-diff`,
  `semantic-merge`) silently kept only the last one — hiding the others from the
  merge gate. Later occurrences are now `anchor#2`, `anchor#3`, …; first
  occurrences keep their existing ids, so manifests for files without repeats
  are unchanged.

## [0.1.0] - 2026-07-24

### Added

- Deterministic semantic chunking, lineage, semantic diff/merge, provenance, and a local agent API.
- Optional DeerFlow operator tooling and semantic CI freshness checks.

[Unreleased]: https://github.com/jesusvilela/aigit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jesusvilela/aigit/releases/tag/v0.1.0
