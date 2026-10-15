# Changelog

All notable changes to AIGit are documented here. The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `aigit merge-driver` / `install-merge-driver`: a Git merge driver for
  `.semantic/` artifacts. Chunk artifacts merge per source file instead of per
  line; a file both sides changed is re-chunked from the merged source,
  following renames, in a merge, rebase, cherry-pick, revert or stash.
  The merged source comes from Git's own ort merge of the three versions, not
  `git merge-file`: ort diffs with histogram, merge-file with Myers, and on
  400 random three-way merges they disagreed 8 times -- twice both merging
  cleanly into different text. Immutable records (`provenance.jsonl`,
  `edges.jsonl`) merge as sets. Merge options that change Git's file merge
  (`-X`, a strategy other than ort, `pull.twohead`, `merge.renormalize`) are
  read off the launching Git command (Linux, macOS, Windows) and ask for
  `aigit chunk` instead; if that command cannot be read, so does the driver. Replaying 150 pairs of
  concurrent edits, adds, deletes and renames on this repository through real
  `git merge`, `git rebase` and `git cherry-pick`: the text merge stopped on
  artifacts alone 41-44 times per mode; the driver never did, and every result
  whose source merged cleanly matched a rebuild exactly. The 20 genuine source
  conflicts are unchanged. 300 adversarial merges of low-entropy files, where
  the two diff algorithms disagree, also all matched a rebuild when clean.
- Semantic Merge workflow (`scripts/resolve_semantic_conflicts.sh`): hosted
  merge buttons run no custom driver, so when GitHub reports a pull request as
  conflicting and the conflict is only in `.semantic/`, it merges the base in
  with the driver and pushes. Source conflicts, stale results and forks are
  left alone. Pushes made with the default token start no workflows, so it
  dispatches CI on each branch it pushes (or set `AIGIT_BOT_TOKEN`).
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

- Every chunk records `file_hash`, the Git blob id of its whole file as the
  parsers read it (line endings normalised, so CRLF and LF checkouts agree),
  making a file's records a one-to-one function of that text. The merge driver
  reads each side's source by this id. Git calls a merge driver
  only when the two sides' artifacts differ, and when two branches each
  inserted a line above every chunk of a file, both recorded the same +1 shift:
  Git kept it, and the merged file -- shifted by two -- had stale artifacts.
  Now two versions of a file never share records, so even a plain text merge
  either conflicts or is exact.
  The field is additive, so `schema_version` is unchanged; artifacts written
  before it merge as before until rebuilt.
- A file a parser finds no chunks in (a Python module of imports and
  constants, an empty Markdown file) is chunked as one opaque `file` chunk.
  Edits to it used to be invisible to `semantic-diff` and `semantic-merge`. A
  file that fails to parse is still reported as an error, and now appears this
  way rather than not at all.
- `aigit chunk` lists files through Git (tracked, plus untracked files that are
  not ignored), so ignored local state -- logs, coverage reports -- no longer
  leaks into the manifest and makes one commit chunk differently on two
  machines. Outside a Git work tree it walks the directory as before.

- CI now smoke-tests the built wheel outside the source checkout.

### Removed

- Identity carry-over from the previous `chunk_index.json`. Chunk ids have
  always been a pure hash of path, anchor and type, and the index is keyed by
  the same triple, so the carried id always equalled the computed one and the
  `refined-anchor` edges it was meant to emit never appeared. A build now
  depends on the source alone.

### Fixed

- Decorators are part of the definition they decorate. `node.lineno` is the
  `def`/`class` line, so decorators sat outside the chunk entirely: rewriting
  `@app.route("/users")` to `@app.route("/admin")` left the content hash
  untouched, `semantic-diff` reported no change, and two branches editing the
  same decorator differently never raised `modify/modify`. Python chunks now
  start at the first decorator, and take their `body_fingerprint` span from the
  AST so that decorators and multi-line signatures stay out of it -- the two
  fingerprints answer different questions and must not be confused.
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
