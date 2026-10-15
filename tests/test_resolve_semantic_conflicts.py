"""scripts/resolve_semantic_conflicts.sh against a local origin and a stub `gh`."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aigit.core import build_manifest, render_manifest, write_manifest

pytestmark = pytest.mark.skipif(
    os.name == 'nt', reason='resolver integration requires a POSIX shell, paths and executable stubs',
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / 'scripts' / 'resolve_semantic_conflicts.sh'
BASE = 'def a():\n    return 1\n\n\ndef b():\n    return 2\n'
STUB_GH = """#!/usr/bin/env bash
case "$*" in
  *headRefName*) printf 'feature\\tmain\\tfalse\\n' ;;
  'pr list'*) echo 7 ;;
  'workflow run'*) echo "$*" >> "$STUB_LOG" ;;
  'run list'*) echo "$STUB_PENDING_RUN" ;;
  'api -X POST'*) echo "$*" >> "$STUB_LOG"; [ -z "$STUB_APPROVE_FAILS" ] ;;
  *pulls/7*) printf '%s\\t%s\\n' "$STUB_MERGEABLE" "$STUB_MERGE_SHA" ;;
  *commits/*) echo "$STUB_MERGE_PARENT" ;;
esac
"""


def _run(cwd: Path, *args: str, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, env=env, text=True, capture_output=True, check=check)


@pytest.fixture
def setup(tmp_path):
    origin, work = tmp_path / 'origin.git', tmp_path / 'work'
    _run(tmp_path, 'git', 'init', '-q', '--bare', '-b', 'main', str(origin))
    _run(tmp_path, 'git', 'clone', '-q', str(origin), str(work))
    for key, value in (('user.email', 't@example.com'), ('user.name', 't')):
        _run(work, 'git', 'config', key, value)
    (work / '.gitignore').write_text('.semantic/cache/\n', encoding='utf-8')
    (work / '.gitattributes').write_text('.semantic/manifest.jsonl merge=aigit-semantic\n'
                                         '.semantic/chunk_index.json merge=aigit-semantic\n', encoding='utf-8')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'gh').write_text(STUB_GH, encoding='utf-8')
    (bin_dir / 'gh').chmod(0o755)
    env = {
        **os.environ,
        'PATH': f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        'PYTHON': sys.executable,
        'PYTHONPATH': str(REPO_ROOT),
        'STUB_MERGEABLE': 'false',
        'AIGIT_MERGEABLE_ATTEMPTS': '1',
        'STUB_LOG': str(tmp_path / 'gh.log'),
    }

    def commit(branch: str, text: str) -> None:
        _run(work, 'git', 'checkout', '-q', '-B', branch, *([] if branch == 'main' else ['origin/main']))
        (work / 'm.py').write_text(text, encoding='utf-8')
        chunks, edges = build_manifest(work)
        write_manifest(chunks, edges, work)
        _run(work, 'git', 'add', '-A')
        _run(work, 'git', 'commit', '-qm', branch)
        _run(work, 'git', 'push', '-q', 'origin', branch)

    commit('main', BASE)
    return work, env, commit


def _resolve(work: Path, env: dict) -> subprocess.CompletedProcess:
    _run(work, 'git', 'checkout', '-q', 'main')
    return _run(work, 'bash', str(SCRIPT), '7', env=env)


def test_semantic_only_conflict_is_resolved_and_pushed(setup):
    work, env, commit = setup
    commit('feature', '# top\n' + BASE)
    _run(work, 'git', 'checkout', '-q', 'main')
    commit('main', BASE + '\n\ndef c():\n    return 3\n')

    result = _resolve(work, env)

    assert 'pushed' in result.stdout, result.stdout + result.stderr
    _run(work, 'git', 'fetch', '-q', 'origin')
    _run(work, 'git', 'checkout', '-q', '--detach', 'origin/feature')
    _run(work, 'git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD')
    on_disk = tuple((work / '.semantic' / n).read_text(encoding='utf-8')
                    for n in ('manifest.jsonl', 'edges.jsonl', 'chunk_index.json'))
    assert on_disk == render_manifest(*build_manifest(work))


def test_source_conflict_is_left_for_the_author(setup):
    work, env, commit = setup
    commit('feature', BASE.replace('return 2', 'return 20'))
    before = _run(work, 'git', 'rev-parse', 'origin/feature').stdout
    _run(work, 'git', 'checkout', '-q', 'main')
    commit('main', BASE.replace('return 2', 'return 21'))

    result = _resolve(work, env)

    assert 'left for the author' in result.stdout
    _run(work, 'git', 'fetch', '-q', 'origin')
    assert _run(work, 'git', 'rev-parse', 'origin/feature').stdout == before


def test_mergeable_pull_request_is_not_touched(setup):
    work, env, commit = setup
    commit('feature', '# top\n' + BASE)
    before = _run(work, 'git', 'rev-parse', 'origin/feature').stdout
    base_tip = _run(work, 'git', 'rev-parse', 'origin/main').stdout.strip()

    result = _resolve(work, {**env, 'STUB_MERGEABLE': 'true', 'STUB_MERGE_SHA': 'abc', 'STUB_MERGE_PARENT': base_tip})

    assert 'no conflict' in result.stdout, result.stdout + result.stderr
    assert _run(work, 'git', 'rev-parse', 'origin/feature').stdout == before


def test_a_verdict_against_an_older_base_is_not_trusted(setup):
    # Seen live: right after the base moved, GitHub still called a now
    # conflicting pull request mergeable, from a trial merge on the old base.
    work, env, commit = setup
    commit('feature', '# top\n' + BASE)

    result = _resolve(work, {**env, 'STUB_MERGEABLE': 'true', 'STUB_MERGE_SHA': 'abc', 'STUB_MERGE_PARENT': 'an-older-base'})

    assert 'no verdict against the current main' in result.stdout, result.stdout + result.stderr


def test_a_refused_push_does_not_stop_the_run(setup):
    work, env, commit = setup
    commit('feature', '# top\n' + BASE)
    _run(work, 'git', 'checkout', '-q', 'main')
    commit('main', BASE + '\n\ndef c():\n    return 3\n')
    hook = Path(_run(work, 'git', 'config', 'remote.origin.url').stdout.strip()) / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
    hook.chmod(0o755)

    result = _run(work, 'bash', str(SCRIPT), '7', '7', env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count('push refused') == 2


def _conflicting(work, commit):
    commit('feature', '# top\n' + BASE)
    _run(work, 'git', 'checkout', '-q', 'main')
    commit('main', BASE + '\n\ndef c():\n    return 3\n')


def test_pending_runs_on_the_pushed_commit_are_approved(setup, tmp_path):
    work, env, commit = setup
    _conflicting(work, commit)

    result = _resolve(work, {**env, 'AIGIT_DISPATCH_CI': 'ci.yml', 'STUB_PENDING_RUN': '4242'})

    assert 'approved' in result.stdout, result.stdout + result.stderr
    log = (tmp_path / 'gh.log').read_text(encoding='utf-8')
    assert 'actions/runs/4242/approve' in log
    assert 'workflow run' not in log


def test_ci_is_dispatched_when_approval_is_not_allowed(setup, tmp_path):
    work, env, commit = setup
    _conflicting(work, commit)

    result = _resolve(work, {**env, 'AIGIT_DISPATCH_CI': 'ci.yml', 'STUB_PENDING_RUN': '4242', 'STUB_APPROVE_FAILS': '1'})

    assert 'dispatched ci.yml' in result.stdout, result.stdout + result.stderr
    assert 'workflow run ci.yml --ref feature' in (tmp_path / 'gh.log').read_text(encoding='utf-8')
