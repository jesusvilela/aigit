# Changelog

All notable changes to AIGit are documented here. The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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
