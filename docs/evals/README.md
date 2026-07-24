# AIGit evaluation program

The job of evaluation is not to prove that AIGit is impressive. It is to find the boundary where its semantic representation is useful, misleading, or too expensive.

## Order of evidence

| Stage | Question | Primary evidence | Beta relevance |
| --- | --- | --- | --- |
| E0 | Is output deterministic? | repeated clean rebuilds of the same snapshot | release blocker |
| E1 | Are chunk boundaries useful? | labeled parser fixture precision/recall | beta blocker |
| E2 | Does identity survive real refactors? | labeled lineage replay suite | beta blocker |
| E3 | Do semantic reports help review? | blinded reviewer task comparison | beta decision gate |
| E4 | Are merge-risk signals calibrated? | historical merge-conflict corpus | beta decision gate |
| E5 | Is the tool fast enough for CI? | repository-size benchmark budget | beta blocker for supported scale |

Run the stages in order. A later stage cannot compensate for a broken earlier one.

## Evaluation rules

- Keep fixtures and labels versioned in the repository.
- Record the AIGit commit, ruleset version, environment, commands, and raw output for every run.
- Separate exploratory measurements from confirmatory claims.
- Preregister any public comparative, accuracy, or developer-productivity claim before collecting the decisive data.
- Publish failures and counterexamples in the [development journal](../DEVELOPMENT_JOURNAL.md).

## Initial artifact layout

```text
docs/
  evals/
    README.md                 # program and protocol
    results/                  # dated, immutable result summaries
  prereg/
    TEMPLATE.md               # claim-level preregistration template
    2026-07-beta-core.md      # first beta evidence plan
```

The fixture harness belongs in `tests/` when it becomes executable; results belong under `docs/evals/results/` when they become reviewable evidence.

## First executable evaluation

The initial lineage replay corpus is [`tests/fixtures/lineage_replay_v1.json`](../../tests/fixtures/lineage_replay_v1.json). Run it with the preregistered beta-core thresholds:

```bash
aigit eval-lineage \
  --fixtures tests/fixtures/lineage_replay_v1.json \
  --min-precision 0.95 \
  --min-recall 0.90 \
  --output docs/evals/results/lineage-replay-v1.json
```

The command emits a deterministic report and fails closed when a threshold is missed. The small checked-in corpus validates the mechanism; beta promotion still requires the preregistered parser-family coverage and design-partner fixtures.
