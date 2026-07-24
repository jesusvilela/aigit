# Lineage replay v1 — 2026-07-24

## Status

Mechanism validation only. This result demonstrates that the evaluation command, fixture format, thresholds, and CI gate work together. It does not support a beta-quality claim.

## Locked inputs

- Fixture: [`tests/fixtures/lineage_replay_v1.json`](../../../tests/fixtures/lineage_replay_v1.json)
- Command:

  ```bash
  aigit eval-lineage \
    --fixtures tests/fixtures/lineage_replay_v1.json \
    --min-precision 0.95 \
    --min-recall 0.90
  ```

- Ruleset: committed `.semantic/ruleset.yaml`
- Environment: local Python 3.12 validation run

## Result

| Metric | Result | Threshold |
| --- | ---: | ---: |
| Cases | 4 | mechanism seed |
| Expected lineage edges | 3 | — |
| False positives | 0 | — |
| False negatives | 0 | — |
| Precision | 1.000 | 0.950 |
| Recall | 1.000 | 0.900 |

The unrelated-change scenario generated no lineage edge. The three positive scenarios matched their expected move/rename/refactor classification.

## Interpretation

The evaluation path is ready to receive a real corpus. The next result must record the locked AIGit commit, ruleset, fixture source, parser-family breakdown, and any deviations from the [beta-core preregistration](../../prereg/2026-07-beta-core.md).
