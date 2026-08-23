"""Corner cases for the semantic layer that autonomous crews actually hit.

These are the edges an async agent crew exercises constantly and where a silent
wrong answer is worse than a loud one: parallel duplicate work, a rename racing
a delete, cosmetic-only edits, and non-ASCII sources.
"""
from pathlib import Path

from aigit.core import (
    _content_hash,
    _simhash,
    build_manifest,
    compute_semantic_conflicts,
    compute_semantic_diff,
    parse_python,
)


def _rec(sid, body, path="m.py", anchor="f", chunk_type="function"):
    return {
        "semantic_id": sid,
        "path": path,
        "anchor": anchor,
        "chunk_type": chunk_type,
        "content_hash": _content_hash(body),
        "fingerprint": _simhash(body),
        "start_line": 1,
        "end_line": 1 + len(body.splitlines()),
    }


BODY = (
    "def pick_provider(model):\n"
    "    for provider in _PROVIDERS:\n"
    "        if model in provider['models']:\n"
    "            return provider['name']\n"
    "    return 'fallback'\n"
)


def test_merge_queue_blocks_every_later_duplicate() -> None:
    """Three agents, same function, different bodies: the queue integrates the
    first and must block both later arrivals, not just the second."""
    trunk = {"s1": _rec("s1", "return 'a'", anchor="pick_provider")}
    second = {"s1": _rec("s1", "return 'b'", anchor="pick_provider")}
    third = {"s1": _rec("s1", "return 'c'", anchor="pick_provider")}
    for candidate in (second, third):
        (conflict,) = compute_semantic_conflicts({}, trunk, candidate)
        assert conflict["kind"] == "add/add"


def test_parallel_duplicate_work_blocks_the_queue_under_a_different_name() -> None:
    """The same ticket solved twice under two names still blocks the merge."""
    trunk = {"s1": _rec("s1", BODY, anchor="pick_provider")}
    other_agent = {"s2": _rec("s2", BODY, anchor="choose_provider")}
    (conflict,) = compute_semantic_conflicts({}, trunk, other_agent)
    assert conflict["kind"] == "duplicate-work"
    assert conflict["anchor"] == "pick_provider"
    assert conflict["theirs_anchor"] == "choose_provider"


def test_unrelated_remove_and_add_is_not_reported_as_a_rename() -> None:
    """Lineage must not invent a refactor from an unrelated delete + add."""
    before = {"s1": _rec("s1", "x = sum(range(10))\nreturn x * 2 - 1", anchor="alpha")}
    after = {"s2": _rec("s2", "raise NotImplementedError('todo')", anchor="zeta")}
    diff = compute_semantic_diff(before, after)
    assert not diff["lineage"]
    assert len(diff["added"]) == 1 and len(diff["removed"]) == 1


def test_whitespace_only_edit_is_not_a_semantic_change() -> None:
    """Cosmetic reformatting must not wake the merge gate."""
    assert _content_hash("def f():\n    return 1") == _content_hash("def f():   \n    return 1    \n")


def test_non_ascii_sources_chunk_deterministically() -> None:
    source = 'def grüße(nom):\n    return f"¡Hola {nom}! café ☕"\n'
    first = [c.content_hash for c in parse_python("u.py", source)]
    second = [c.content_hash for c in parse_python("u.py", source)]
    assert first and first == second


def test_unparseable_file_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    """A model that emits prose instead of code must surface as an error the
    strict gate can fail on, rather than an empty, clean-looking manifest."""
    (tmp_path / "broken.py").write_text("I'm sorry, but I can't do that.\n", encoding="utf-8")
    errors: list[dict[str, str]] = []
    chunks, _ = build_manifest(tmp_path, errors)
    assert [e["path"] for e in errors] == ["broken.py"]
    assert not [c for c in chunks if c.path.endswith("broken.py")]


# --------------------------------------------------------------------------- #
# End-to-end: the same check the merge queue runs, over real git refs.
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ['git', *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def _agent_branch(repo: Path, branch: str, base: str, func_name: str) -> None:
    """An agent solves the ticket under its own chosen name, then re-chunks."""
    import argparse

    from aigit import core

    _git(repo, 'checkout', '-q', base)
    _git(repo, 'checkout', '-q', '-b', branch)
    (repo / 'pkg' / 'providers.py').write_text(
        '_PROVIDERS = [{"name": "openai", "models": ["gpt-4o"]}]\n\n\n'
        f'def {func_name}(model):\n'
        '    for provider in _PROVIDERS:\n'
        "        if model in provider['models']:\n"
        "            return provider['name']\n"
        "    return 'fallback'\n",
        encoding='utf-8',
    )
    core.cmd_chunk(argparse.Namespace(repo=str(repo), strict=False, check=False))
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', f'{branch}: {func_name}')


def test_duplicate_work_across_real_branches_blocks_the_merge(tmp_path, monkeypatch) -> None:
    """Two agents ship the same behaviour under different names on two
    branches; the merge gate must stop the second one."""
    import argparse

    from aigit import core

    repo = tmp_path
    _git(repo, 'init', '-q', '.')
    _git(repo, 'config', 'user.email', 'crew@test')
    _git(repo, 'config', 'user.name', 'crew')
    (repo / 'pkg').mkdir()
    (repo / 'pkg' / 'providers.py').write_text(
        '_PROVIDERS = [{"name": "openai", "models": ["gpt-4o"]}]\n', encoding='utf-8'
    )
    core.cmd_chunk(argparse.Namespace(repo=str(repo), strict=False, check=False))
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'seed')
    base = _git(repo, 'rev-parse', 'HEAD')

    _agent_branch(repo, 'agent-a', base, 'pick_provider')
    _agent_branch(repo, 'agent-b', base, 'choose_provider')

    # _read_manifest_from_ref shells out to git in the process cwd
    monkeypatch.chdir(repo)
    out = repo / 'merge.json'
    core.cmd_merge(
        argparse.Namespace(
            base=base, ours='agent-a', theirs='agent-b',
            output=str(out), no_duplicate_work=False,
        )
    )
    import json

    conflicts = json.loads(out.read_text(encoding='utf-8'))['conflicts']
    assert [c['kind'] for c in conflicts] == ['duplicate-work']
    assert {conflicts[0]['anchor'], conflicts[0]['theirs_anchor']} == {
        'pick_provider', 'choose_provider'
    }

    # ...and the escape hatch really disables it
    core.cmd_merge(
        argparse.Namespace(
            base=base, ours='agent-a', theirs='agent-b',
            output=str(out), no_duplicate_work=True,
        )
    )
    assert json.loads(out.read_text(encoding='utf-8'))['conflicts'] == []
