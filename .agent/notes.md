# Repair checkpoint — 2026-10-15

- Fetched origin; main remains at the pinned testbed source commit 25dae732.
- Reproduced TS body, YAML nested/list/block-scalar omissions with source regressions.
- Added conservative full-section hashes and line ranges; bumped parse cache to 6.
- Provenance and HTTP defects reproduced and repaired; independent review also
  caught division/regex ambiguity and loss of existing file modes. Both have
  explicit regressions and corrective implementation.
- Same 112 tests on pinned baseline: 93 failures, zero setup errors; repaired
  Windows run: 111 passes, one POSIX mode skip. Linux Python 3.10: 133 passes,
  including POSIX modes, symlinks and shell resolver tests.
- Full Windows run initially found 11 host/fixture failures. Tests now check
  unavailable symlink/POSIX capabilities, compare physical byte counts, and use
  isolated fixture roots. Final complete Windows run: 282 passed, 18 skipped,
  688.43 seconds. The skipped POSIX cases passed in the Linux focused run.
- Commands: `python -m pytest -q --basetemp=../pytest-aigit-full-final --durations=10
  --junitxml=.aigit/runtime/validation-repairs/full-suite-final.xml`;
  Linux focused run covered the three new regression modules, legacy provenance,
  publication hygiene, symlink filtering and the resolver integration module.
- POSIX strict chunk rebuild/freshness and lineage precision/recall gates passed.
- Repair code commit f3c2b60 pushed; GitHub CI run 38752325983 passed Python
  3.10/3.11/3.12 validation, semantics, lockfile and distribution smoke checks.
- Earlier disposable pytest fixtures were removed after retaining raw JUnit
  reports; they can be regenerated with the recorded commands.
- The previous testbed matrix/provenance scripts do not exercise the stated AIGit
  scenarios; copied label fields are not independent annotation. Correct their
  interpretation in the testbed and do not cite them as validation of these fixes.
