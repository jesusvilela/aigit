"""The merge driver must agree with a rebuild of the merged source, or say it cannot."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from aigit import core
from aigit.core import (
    _strategy_overrides,
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


def test_edits_that_shift_chunks_alike_still_differ(tmp_path):
    # Each side shifts every chunk in a.py down one line. Without the file
    # hash both sides' records were identical, Git kept them without asking
    # the driver, and the merged source -- shifted by two -- went stale.
    o = _snapshot(tmp_path, BASE)
    a = _snapshot(tmp_path, {**BASE, 'a.py': '# one\n' + BASE['a.py']})
    b = _snapshot(tmp_path, {**BASE, 'a.py': '# two\n' + BASE['a.py']})
    assert a[0] != b[0]
    merged, needs_rebuild = merge_semantic_artifact('manifest.jsonl', o[0], a[0], b[0])
    assert needs_rebuild == ['a.py']


def test_file_without_definitions_is_still_chunked(tmp_path):
    o = _snapshot(tmp_path, {**BASE, 'c.py': 'import os\n'})
    a = _snapshot(tmp_path, {**BASE, 'c.py': 'import os\nimport sys\n'})
    assert '"path": "c.py"' in o[0]
    assert o[0] != a[0]


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


def _assert_fresh(repo: Path) -> None:
    """Artifacts in the work tree equal what a rebuild of the merged source writes."""
    on_disk = tuple(
        (repo / '.semantic' / name).read_text(encoding='utf-8')
        for name in ('manifest.jsonl', 'edges.jsonl', 'chunk_index.json')
    )
    assert on_disk == _artifacts(repo)


def _diverge_on_one_file(repo: Path) -> None:
    # Both sides edit a.py at different places: the source merges cleanly,
    # but every chunk record of a.py differs on each side.
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'a.py': '# top\n' + BASE['a.py']}, 'feature edits a')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main edits a')


def test_git_merge_rechunks_a_file_both_sides_changed(repo):
    _diverge_on_one_file(repo)

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / 'a.py').read_text(encoding='utf-8').startswith('# top\n')
    _assert_fresh(repo)


def test_git_merge_of_alike_shifts_is_fresh(repo):
    # Both sides insert one line between a() and a2(), at different places:
    # Git merges the source cleanly and each side shifted a2 by exactly one.
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'a.py': BASE['a.py'].replace('\n\ndef a2', '\n\n# f\ndef a2')}, 'feature')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'].replace('return 1\n', 'return 1\n# m\n')}, 'main')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / 'a.py').read_text(encoding='utf-8').count('#') == 2
    _assert_fresh(repo)


def test_edit_follows_a_rename_on_the_other_side(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _git(repo, 'mv', 'a.py', 'moved.py')
    _commit_snapshot(repo, {}, 'feature renames a')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main edits a')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'def a3' in (repo / 'moved.py').read_text(encoding='utf-8')
    _assert_fresh(repo)


def test_modify_delete_is_left_to_git(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _git(repo, 'rm', '-q', 'a.py')
    _commit_snapshot(repo, {}, 'feature deletes a')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main edits a')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode != 0
    assert 'a.py' in _git(repo, 'diff', '--name-only', '--diff-filter=U').stdout


def test_rebase_rechunks_a_file_both_sides_changed(repo):
    _diverge_on_one_file(repo)
    _git(repo, 'checkout', '-q', 'feature')

    result = _git(repo, 'rebase', 'main', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(repo)


def test_cherry_pick_reads_sources_by_blob_id(repo):
    # Git leaves no trace of the commit a cherry-pick applies; the chunks name
    # their file's blob, which is enough.
    _diverge_on_one_file(repo)

    result = _git(repo, 'cherry-pick', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(repo)


def test_cherry_pick_follows_a_rename(repo):
    # The picked commit is read off the `git cherry-pick` command line.
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'feature edits a')
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'mv', 'a.py', 'moved.py')
    _commit_snapshot(repo, {}, 'main renames a')

    result = _git(repo, 'cherry-pick', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'def a3' in (repo / 'moved.py').read_text(encoding='utf-8')
    _assert_fresh(repo)


def test_merged_source_is_what_git_merges_not_what_merge_file_says(repo):
    # Found by fuzzing: `git merge-file` (Myers) and ort (histogram) both
    # merge these cleanly, into different text. Chunking merge-file's answer
    # left the artifacts describing a file Git never wrote.
    base, ours, theirs = 'z\n{\nx\n{\nx\nx\n', 'z\ny\nx\n{\nx\n{\nx\n', 'z\n{\nx\n{\n{\nx\nx\n'
    _commit_snapshot(repo, {'notes.md': base}, 'notes')
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'notes.md': theirs}, 'feature')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'notes.md': ours}, 'main')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(repo)


def test_explicit_ort_and_a_dash_x_message_still_rebuild(repo):
    _diverge_on_one_file(repo)

    result = _git(repo, 'merge', '-s', 'ort', '-m', '-Xnot an option', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(repo)


@pytest.mark.parametrize(
    'args, overridden',
    [
        (['merge', 'feature'], False),
        (['merge', '-s', 'ort', 'feature'], False),
        (['merge', '--strategy=ort', 'feature'], False),
        (['merge', '-m', '-Xours', 'feature'], False),
        (['merge', '-Xours', 'feature'], True),
        (['merge', '-X', 'patience', 'feature'], True),
        (['rebase', '--strategy-option=theirs', 'main'], True),
        (['merge', '-s', 'resolve', 'feature'], True),
        (['merge', '-sresolve', 'feature'], True),
    ],
)
def test_strategy_override_parsing(args, overridden):
    assert _strategy_overrides(args) is overridden


def test_unreadable_launching_process_declines(repo, monkeypatch):
    monkeypatch.setattr(core, '_git_parent_args', lambda: None)
    assert core._merge_is_overridden(repo) is True


def test_another_two_head_strategy_declines(repo):
    _diverge_on_one_file(repo)
    _git(repo, 'config', 'pull.twohead', 'resolve')
    assert core._merge_is_overridden(repo) is True


def test_strategy_options_decline_the_rebuild(repo):
    # -X ignore-space-change changes Git's file merge, so the driver must not
    # predict it with a plain one.
    _diverge_on_one_file(repo)

    result = _git(repo, 'merge', '--no-edit', '-Xignore-space-change', 'feature', check=False)

    assert result.returncode != 0
    assert 'run `aigit chunk`' in result.stderr


def test_renormalize_declines_the_rebuild(repo):
    _diverge_on_one_file(repo)
    _git(repo, 'config', 'merge.renormalize', 'true')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode != 0


def test_crlf_checkout_chunks_like_lf(tmp_path):
    (tmp_path / 'a.py').write_bytes(BASE['a.py'].encode())
    lf = _artifacts(tmp_path)
    (tmp_path / 'a.py').write_bytes(BASE['a.py'].replace('\n', '\r\n').encode())
    assert _artifacts(tmp_path) == lf


def test_source_conflict_leaves_the_artifacts_conflicted_too(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'b.py': 'def b():\n    return 2\n'}, 'feature')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'b.py': 'def b():\n    return 3\n'}, 'main')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode != 0
    assert 'b.py' in result.stderr


def test_stale_artifacts_are_not_trusted_as_evidence(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'a.py': '# top\n' + BASE['a.py']}, 'feature edits a')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main edits a')
    # Commit a source edit on main without refreshing its artifacts.
    (repo / 'a.py').write_text(BASE['a.py'] + '\n\ndef a4():\n    return 4\n', encoding='utf-8')
    _git(repo, 'commit', '-qam', 'stale')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode != 0
    assert 'run `aigit chunk`' in result.stderr


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


def test_merge_of_a_branch_with_stale_artifacts_is_not_trusted(repo):
    # The stale artifact matches the branch's *parent*; only the exact commit
    # being merged may be used, or the wrong source would be chunked.
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {'a.py': '# top\n' + BASE['a.py']}, 'feature')
    (repo / 'a.py').write_text('# top\n# unchunked\n' + BASE['a.py'], encoding='utf-8')
    _git(repo, 'commit', '-qam', 'stale')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode != 0
    assert 'run `aigit chunk`' in result.stderr


def test_revert_of_an_older_commit(repo):
    _commit_snapshot(repo, {'a.py': BASE['a.py'].replace('return 2', 'return 20')}, 'change a2')
    _commit_snapshot(repo, {'a.py': '# later\n' + BASE['a.py'].replace('return 2', 'return 20')}, 'later')

    result = _git(repo, 'revert', '--no-edit', 'HEAD~1', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'return 2\n' in (repo / 'a.py').read_text(encoding='utf-8')
    _assert_fresh(repo)


def test_stash_pop_over_a_newer_commit(repo):
    (repo / 'a.py').write_text('# wip\n' + BASE['a.py'], encoding='utf-8')
    chunks, edges = build_manifest(repo)
    write_manifest(chunks, edges, repo)
    _git(repo, 'stash', '-q')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '\n\ndef a3():\n    return 3\n'}, 'main')

    result = _git(repo, 'stash', 'pop', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(repo)


def test_branches_that_adopted_aigit_separately(tmp_path, monkeypatch):
    # Neither the merge base nor anything before it has artifacts: the driver
    # gets an empty base and must read the base source from the merge base.
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'config', 'user.email', 'test@example.com')
    _git(tmp_path, 'config', 'user.name', 'test')
    monkeypatch.chdir(tmp_path)
    assert cmd_install_merge_driver(type('Args', (), {'repo': str(tmp_path)})()) == 0
    (tmp_path / '.gitignore').write_text('.semantic/cache/\n', encoding='utf-8')
    (tmp_path / 'a.py').write_text(BASE['a.py'], encoding='utf-8')
    _git(tmp_path, 'add', '-A')
    _git(tmp_path, 'commit', '-qm', 'before aigit')  # routing in place, no artifacts yet
    _git(tmp_path, 'checkout', '-qb', 'feature')
    _commit_snapshot(tmp_path, {'a.py': '# top\n' + BASE['a.py']}, 'feature adopts')
    _git(tmp_path, 'checkout', '-q', 'main')
    shutil.rmtree(tmp_path / '.semantic', ignore_errors=True)  # main adopts on its own
    _commit_snapshot(tmp_path, {'a.py': BASE['a.py'] + '# main\n', 'b.py': BASE['b.py']}, 'main adopts')

    result = _git(tmp_path, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(tmp_path)


def test_edit_merges_into_a_file_renamed_out_of_the_layer(repo):
    _git(repo, 'checkout', '-qb', 'feature')
    _git(repo, 'mv', 'a.py', 'a.png')
    _commit_snapshot(repo, {}, 'feature renames a to an excluded type')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {'a.py': BASE['a.py'] + '# main\n'}, 'main edits a')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"a.py"' not in (repo / '.semantic' / 'manifest.jsonl').read_text(encoding='utf-8')
    _assert_fresh(repo)


def test_symlinks_are_not_chunked(tmp_path):
    (tmp_path / 'target.py').write_text(BASE['a.py'], encoding='utf-8')
    (tmp_path / 'link.py').symlink_to('target.py')
    paths = {record['path'] for record in map(json.loads, _artifacts(tmp_path)[0].splitlines())}
    assert paths == {'target.py'}


def test_many_contested_files_merge_in_one_pass(repo):
    files = {f'f{i}.py': BASE['a.py'] for i in range(40)}
    _commit_snapshot(repo, files, 'many')
    _git(repo, 'checkout', '-qb', 'feature')
    _commit_snapshot(repo, {name: '# top\n' + text for name, text in files.items()}, 'feature')
    _git(repo, 'checkout', '-q', 'main')
    _commit_snapshot(repo, {name: text + '# main\n' for name, text in files.items()}, 'main')

    result = _git(repo, 'merge', '--no-edit', 'feature', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(repo)


def test_branch_cut_before_the_routing_still_uses_the_driver(tmp_path, monkeypatch):
    # .gitattributes routes the artifacts only from the commit that added it;
    # merging main into an older branch must still go through the driver.
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'config', 'user.email', 'test@example.com')
    _git(tmp_path, 'config', 'user.name', 'test')
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.gitignore').write_text('.semantic/cache/\n', encoding='utf-8')
    _commit_snapshot(tmp_path, BASE, 'base, no routing')
    _git(tmp_path, 'checkout', '-qb', 'old-branch')
    _commit_snapshot(tmp_path, {'a.py': '# top\n' + BASE['a.py']}, 'old branch')
    _git(tmp_path, 'checkout', '-q', 'main')
    assert cmd_install_merge_driver(type('Args', (), {'repo': str(tmp_path)})()) == 0
    _commit_snapshot(tmp_path, {'a.py': BASE['a.py'] + '# main\n'}, 'main routes and edits')
    _git(tmp_path, 'checkout', '-q', 'old-branch')
    assert not (tmp_path / '.gitattributes').exists()

    result = _git(tmp_path, 'merge', '--no-edit', 'main', check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_fresh(tmp_path)
