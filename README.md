# AIGit

AI-native semantic version control layer built on top of Git.

AIGit keeps Git fully intact and adds a deterministic semantic chunk graph in `.semantic/` so both humans and agents can review intent, track lineage, and run semantic workflows.

## MVP capabilities

- Parse supported files into semantic chunks (`.py`, `.md`, and fallback file chunks).
- Assign stable semantic IDs (`sc_<hash>`) and preserve lineage with deterministic matching.
- Persist semantic manifests in version-controlled files under `.semantic/`.
- Track chunk lineage through `edges.jsonl` and `chunk_index.json`.
- Support semantic-aware merge conflict analysis with `semantic-merge`.
- Attach AI provenance via commit trailers and `.semantic/provenance.jsonl`.
- Expose a local chunk API (`serve-api`) for agent tooling.
- Generate semantic diff reports for CI and PR review (`semantic-diff`).

## Repository compatibility

- No custom Git object types.
- Works on normal GitHub/GitLab workflows.
- Degrades safely: if AIGit is missing, files and Git operations still work.

## Semantic storage layout

```text
.semantic/
  schema_version
  ruleset.yaml
  manifest.jsonl
  edges.jsonl
  chunk_index.json
  provenance.jsonl
  cache/              # local-only, gitignored
```

## Quickstart

```bash
python -m pip install -e .
aigit chunk
aigit semantic-diff --base main --head HEAD --output semantic_diff.md
aigit semantic-merge --base main --ours HEAD --theirs feature --output semantic_merge.json
aigit record-provenance --agent codex --model gpt-5.2-codex --prompt "chunk update"
aigit serve-api --host 127.0.0.1 --port 8765
```

## CLI reference

- `aigit chunk` — Rebuild deterministic semantic artifacts for the current repository snapshot.
- `aigit semantic-diff --base <ref> --head <ref> --output <file>` — Generate a PR-ready semantic diff report from committed manifests.
- `aigit semantic-merge --base <ref> --ours <ref> --theirs <ref>` — Detect semantic conflicts where both sides changed the same chunk from base.
- `aigit record-provenance --agent <name> --model <model> --prompt <text>` — Append AI provenance metadata for `HEAD`.
- `aigit commit -m <msg> --agent ... --model ... --prompt ...` — Create a Git commit with an AI provenance trailer.
- `aigit serve-api` — Start a local HTTP server with endpoints:
  - `GET /healthz`
  - `GET /chunks`

## Determinism and safety notes

- Canonicalization uses LF normalization + trailing whitespace trimming.
- Ruleset and schema version are committed, making chunk graph generation reproducible.
- Identity uncertainty is resolved conservatively: if similarity is below threshold, a new semantic ID is assigned.
