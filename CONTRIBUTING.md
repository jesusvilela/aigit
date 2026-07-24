# Contributing to AIGit

Thank you for helping make semantic version control practical.

## The shape of a good contribution

Keep it small, legible, and verifiable. A useful pull request explains:

1. the developer problem it solves;
2. the expected behavior; and
3. how you tested it.

For parser or lineage changes, include a focused fixture or regression test. For documentation changes, favor direct examples over abstract claims.

## Local setup

```bash
git clone https://github.com/jesusvilela/aigit.git
cd aigit
./scripts/bootstrap_uv.sh
uv run pytest -q
```

Before opening a pull request, run:

```bash
uv run pytest -q
./scripts/ci_refresh_semantics.sh
git diff --exit-code -- .semantic
```

Semantic artifacts are part of the repository contract. If your change affects generated `.semantic/` output, rebuild and include the intentional updates in the pull request.

## Pull request guidance

- Keep one clear intent per pull request.
- Add or update tests for behavior changes.
- Do not commit credentials, local caches, vendor directories, or runtime state.
- Describe any compatibility or migration impact plainly.
- Be specific about uncertainty. Alpha feedback is valuable when it is concrete.

## Where to start

- parser coverage and chunk-quality examples;
- lineage edge cases caused by real refactors;
- semantic-diff and semantic-merge report clarity;
- agent API ergonomics and documentation;
- onboarding improvements for first-time users.

The [roadmap](docs/EPICS_ROADMAP.md) captures broader directions. If you want to take on a larger item, open an issue first so the interface remains coherent.

## Community standard

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security concern, follow [SECURITY.md](SECURITY.md) rather than opening a public issue.
