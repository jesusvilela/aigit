"""The merge driver must agree with a rebuild of the merged source, or say it cannot."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from aigit.core import (
    build_manifest,
    cmd_install_merge_driver,
    merge_semantic_artifact,
    render_manifest,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _artifacts(root: Path) -> tuple[str, str, str]:
    chunks, edges = build_manifest(root)
    return render_manifest(chunks, edges)


def _snapshot(tmp_path: Path, files: dict[str, str]) -> tuple[str, str, str]:
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
    for stale in set(p.name for p in tmp_path.glob('*.py')) - set(files):
        (tmp_path / stale).unlink()
    return _artifacts(tmp_path)


BASE = {
    'a.py': 'def a():\n    return 1\n\n\ndef a2():\n    return 2\n',
    'b.py': 'def b():\n    return 1\n',
}


def test_edits_to_different_files_merge_to_the_rebuild(tmp_path):
    o = _snapshot(tmp_path, BASE)
    a = _snapshot(tmp_path, {**BASE, 'a.py': '# header\n' + BASE['a.py']})
    b = _snapshot(tmp_path, {**BASE, 'b.py': BASE['b.py'] + '\n\ndef c():\n    return 3\n'})
    truth = _snapshot(
        tmp_path,
        {'a.py': '# header\n' + BASE['a.py'], 'b.py': BASE['b.py'] + '\n\ndef c():\n    return 3\n'},
    )
    for i, name in ((0, 'manifest.jsonl'), (2, 'chunk_index.json')):
        merged, needs_rebuild = merge_semantic_artifact(name, o[i], a[i], b[i])
        assert needs_rebuild == []
        assert merged == truth[i]


def test_deleting_a_file_on_one_side_drops_its_chunks(tmp_path):
    o = _snapshot(tmp_path, BASE)
    a = _snapshot(tmp_path, {'a.py': BASE['a.py']})
    b = _snapshot(tmp_path, {**BASE, 'a.py': BASE['a.py'] + '\n\ndef z():\n    pass\n'})
    merged, needs_rebuild = merge_semantic_artifact('manifest.jsonl', o[0], a[0], b[0])
    assert needs_rebuild == []
    assert 'b.py' not in merged
    assert '"anchor": "z"' in merged


def test_identical_line_shifts_on_both_sides_are_not_trusted(tmp_path):
    # Each side shifts every chunk in a.py down one line, so the two sides'
    # records are equal -- yet the merged source shifts them by two.
    o = _snapshot(tmp_path, BASE)
    a = _snapshot(tmp_path, {**BASE, 'a.py': '# one\n' + BASE['a.py']})
    b = _snapshot(tmp_path, {**BASE, 'a.py': '# two\n' + BASE['a.py']})
    assert a[0] == b[0]
    merged, needs_rebuild = merge_semantic_artifact('manifest.jsonl', o[0], a[0], b[0])
    assert needs_rebuild == ['a.py']
    assert merged == a[0]


def test_concurrent_provenance_appends_both_survive():
    row = lambda n: json.dumps({'commit': n, 'agent': 'x'}, sort_keys=True)
    base = row('c0') + '\n'
    ours = base + row('c1') + '\n'
    theirs = base + row('c2') + '\n'
    merged, needs_rebuild = merge_semantic_artifact('provenance.jsonl', base, ours, theirs)
    assert needs_rebuild == []
    assert merged.splitlines() == [row('c0'), row('c1'), row('c2')]
    # A removal on one side is honoured, not resurrected by the other.
    merged, _ = merge_semantic_artifact('provenance.jsonl', base, '', theirs)
    assert merged.splitlines() == [row('c2')]


def test_unknown_artifact_is_refused():
    with pytest.raises(ValueError):
        merge_semantic_artifact('ruleset.yaml', '', '', '')


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, 'PYTHONPATH': str(REPO_ROOT)}
    return subprocess.run(['git', *args], cwd=cwd, env=env, text=True, capture_output=True, check=check)


def _commit_snapshot(repo: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (repo / name).write_text(text, encoding='utf-8')
    chunks, edges = build_manifest(repo)
    write_manifest(chunks, edges, repo)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', message)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'config', 'user.email', 'test@example.com')
    _git(tmp_path, 'config', 'user.name', 'test')
    (tmp_path / '.gitignore').write_text('.semantic/cache/\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    args = type('Args', (), {'repo': str(tmp_path)})()
    assert cmd_install_merge_driver(args) == 0
    # Neighbouring files, so their manifest lines are adjacent: a text merge
    # of the two edits below conflicts, the per-file merge does not.
    _commit_snapshot(tmp_path, BASE, 'base')
    return tmp_path


def test_git_merge_lands_fresh_artifacts_without_a_conflict(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'b.py': '# moved\n' + BASE['b.py']}, 'edit b')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'edit a')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    merged = (repo / '.semantic' / 'manifest.jsonl').read_text(encoding='utf-8')
    assert merged == _artifacts(repo)[0]  # what a rebuild of the merged source writes


def test_git_merge_asks_for_a_rebuild_when_both_sides_touch_one_file(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'a.py': '# top\n' + BASE['a.py']}, 'feature edits a')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main edits a')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode != 0
    assert 'run `aigit chunk`' in result.stderr
    assert (repo / 'a.py').read_text(encoding='utf-8').startswith('# top\n')  # source merged
    assert '<<<<<<<' not in (repo / '.semantic' / 'manifest.jsonl').read_text(encoding='utf-8')
    chunks, edges = build_manifest(repo)
    write_manifest(chunks, edges, repo)
    _git(repo, 'add', '.semantic')
    _git(repo, 'commit', '-qm', 'merge', '--no-edit')


def test_install_leaves_paths_routed_to_another_driver(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    (tmp_path / '.gitattributes').write_text(
        '.semantic/manifest.jsonl filter=lfs diff=lfs merge=lfs -text\n', encoding='utf-8'
    )
    args = type('Args', (), {'repo': str(tmp_path)})()
    assert cmd_install_merge_driver(args) == 0
    lines = (tmp_path / '.gitattributes').read_text(encoding='utf-8').splitlines()
    assert '.semantic/manifest.jsonl filter=lfs diff=lfs merge=lfs -text' in lines
    assert '.semantic/provenance.jsonl merge=aigit-semantic' in lines
    assert not any(line.startswith('.semantic/manifest.jsonl merge=aigit-semantic') for line in lines)
