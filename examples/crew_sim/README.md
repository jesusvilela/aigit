# Agent crew simulation

Six agents in six timezones, each on its own branch, landing work through a
trunk merge queue. The interesting part is not that agents can write code — it
is whether AIGit's gates behave correctly when they write it *concurrently and
imperfectly*.

```bash
python examples/crew_sim/run_crew.py            # deterministic, no network
python examples/crew_sim/run_crew.py --keep /tmp/crew   # keep the repo to inspect
```

Exit status is `0` only if every property holds, so it doubles as a test
(`tests/test_crew_sim.py` runs it in CI).

## What it checks

| Property | The failure it guards against |
| --- | --- |
| `delocalized_async_timeline` | agents acting at one synchronized instant, which hides ordering bugs |
| `strict_gate_blocks_broken_draft` | an unparseable model draft reaching a branch |
| `merge_queue_blocks_same_name_duplicate` | two agents shipping `pick_provider` twice (`add/add`) |
| `merge_queue_blocks_renamed_duplicate` | the same work landing as `choose_provider` (`duplicate-work`) |
| `queue_blocks_reimplementation_of_existing_code` | an agent re-adding what the codebase already had (`duplicate-work`, scope `existing`) |
| `rename_lands_as_lineage` | a refactor reading as delete + add, destroying history |
| `signed_commit_verifies` | attestation that cannot actually validate a legitimate commit |
| `unsigned_commit_rejected` | an unsigned commit slipping into an attested trunk |
| `drift_gate_blocks_stale_state` | a commit whose `.semantic` state was never regenerated |

Duplicate work arrives in three shapes and each needs its own check. `add/add`
is keyed on the identifier, so it only fires when two agents pick the *same*
name. `duplicate-work` with scope `concurrent` catches them picking different
names. Scope `existing` catches the commonest case of all — one agent adding
what the codebase already had, with no second agent involved.

The two name-keyed gates are deliberately separate. `add/add` is keyed on the
identifier, so it only fires when two agents pick the *same* name; agents
working one ticket in parallel frequently don't, which is what `duplicate-work`
is for.

## Running it against a real model

The scenario is backend-agnostic. Deterministic is the default so CI needs
neither network nor weights.

```bash
# any OpenAI-compatible API (OpenAI, Moonshot, vLLM, ollama, llama-server)
AIGIT_CREW_ENDPOINT=https://api.openai.com/v1 \
AIGIT_CREW_MODEL=gpt-4o-mini \
AIGIT_CREW_API_KEY=sk-... \
python examples/crew_sim/run_crew.py

# local weights via transformers
AIGIT_CREW_LOCAL=1 AIGIT_CREW_MODEL=LiquidAI/LFM2-1.2B \
python examples/crew_sim/run_crew.py

# add sampling so agents diverge instead of converging on identical text
AIGIT_CREW_SAMPLE=1 AIGIT_CREW_TEMP=0.9 ...
```

`AIGIT_CREW_DTYPE=bfloat16` is worth setting for larger local checkpoints; a 4B
model in float32 will not fit in 16 GB.

## Notes from running this against real models

Recorded so the deterministic fixtures stay honest about what they stand in for.
These are observations from specific runs, not benchmarks.

- **Small models are competent at syntax, unreliable at semantics.** Across
  LFM2 350M/1.2B/2.6B, Gemma 3 4B and gpt-4o-mini, generated functions
  parsed nearly always, while still referring to symbols that did not exist.
  The gates, not the model, are what keep the trunk coherent.
- **Instruction-following matters more than raw quality here.** Below roughly
  1B parameters, models tended to wrap the answer in a class instead of
  emitting one top-level function. That silently changes the chunk anchor, and
  therefore what the merge gate is comparing — which is why `build_prompt` is
  so blunt about wanting exactly one function.
- **Capable models converge; that is not the same as agreeing.** Under greedy
  decoding, two agents given different style hints sometimes produced
  byte-identical code, which correctly yields no conflict. Divergence — and so
  merge risk — rises with sampling temperature and with mixing model families.
  Use `AIGIT_CREW_SAMPLE=1` when you want to exercise the conflict paths.

## Merging `.semantic/` needs two different rules

Every branch regenerates `.semantic/`, so concurrent branches always collide
there even when their code does not — and the right resolution differs by file:

- **Derived artifacts** (`manifest.jsonl`, `chunk_index.json`) are *rebuilt, not
  merged*: take one side, then re-run the chunker.
- **`provenance.jsonl` is an append-only log**, not derived. Taking one side
  silently discards the other branch's attestation, so the queue unions the rows
  instead.

A conflict anywhere outside `.semantic/` is treated as genuine and stops the queue.

## Properties are asserted against the tool, not the harness

Two of these could easily have been self-fulfilling, so they are deliberately
wired through the real commands:

- **`strict_gate_blocks_broken_draft`** writes the bad draft to disk and runs
  `aigit chunk --strict`, asserting on its error text. Judging the draft with a
  harness-side `ast.parse` would report the property green even if the gate
  stopped rejecting anything.
- **`unsigned_commit_rejected`** — see below.

## Why P4 asserts two things

Rejecting a commit that simply has no provenance trailer proves nothing about
signing — every commit in a fresh repository would be rejected, so the check
could never fail. The unsigned commit here is written by an "intruder" that can
produce commits and log rows but lacks the key: it carries a valid trailer and a
matching row, passes plain `verify-provenance`, and is rejected only under
`--require-signature`. That isolates the signature gate from the trailer gate.
