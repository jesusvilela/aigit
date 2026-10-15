"""Shared harness for the merge-driver experiments.

Every experiment runs real Git in throwaway repositories with the AIGit merge
driver installed, and judges each merge by one question: are the committed
.semantic/ artifacts exactly what `aigit chunk` produces from the merged
source?
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from aigit.core import build_manifest, cmd_install_merge_driver, render_manifest, write_manifest  # noqa: E402

ARTIFACTS = ('manifest.jsonl', 'edges.jsonl', 'chunk_index.json')

# Outcomes, from best to worst. Every merge lands in exactly one.
FRESH = 'fresh'                  # merged cleanly; artifacts equal a rebuild
SOURCE_CONFLICT = 'source'       # stopped: a source file genuinely conflicts
METADATA_ONLY = 'metadata-only'  # stopped: only .semantic/ conflicted (needless)
OTHER_STOP = 'other-stop'        # stopped with nothing unmerged (empty cherry-pick)
STALE = 'stale'                  # merged cleanly; artifacts are wrong (silent)
OUTCOMES = (FRESH, SOURCE_CONFLICT, METADATA_ONLY, OTHER_STOP, STALE)


def environment() -> dict:
    git = subprocess.run(['git', '--version'], text=True, capture_output=True).stdout.split()[-1]
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, text=True, capture_output=True).stdout.strip()
    return {
        'aigit_commit': commit,
        'git': git,
        'python': platform.python_version(),
        'platform': platform.platform(),
    }


class Repo:
    """A throwaway repository with the driver installed."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(tempfile.mkdtemp(prefix='aigit-exp-'))
        self.env = {**os.environ, 'PYTHONPATH': str(REPO_ROOT), 'GIT_EDITOR': 'true'}
        if not (self.root / '.git').exists():
            self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'experiment@example.com')
        self.git('config', 'user.name', 'experiment')
        gitignore = self.root / '.gitignore'
        if not gitignore.exists():
            gitignore.write_text('.semantic/cache/\n', encoding='utf-8')
        self.install_driver()

    def install_driver(self) -> None:
        cmd_install_merge_driver(type('Args', (), {'repo': str(self.root)})())

    def uninstall_driver(self) -> None:
        """Git then falls back to its line-based text merge for the artifacts."""
        self.git('config', '--remove-section', 'merge.aigit-semantic')

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(['git', *args], cwd=cwd or self.root, env=self.env, text=True, capture_output=True)

    def write(self, files: dict) -> None:
        for name, text in files.items():
            path = self.root / name
            if text is None:
                path.unlink(missing_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            (path.write_bytes if isinstance(text, bytes) else path.write_text)(text)

    def chunk(self) -> None:
        chunks, edges = build_manifest(self.root)
        write_manifest(chunks, edges, self.root)

    def commit(self, files: dict | None = None, message: str = 'change', chunk: bool = True) -> str:
        self.write(files or {})
        if chunk:
            self.chunk()
        self.git('add', '-A')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD').stdout.strip()

    def outcome(self, result: subprocess.CompletedProcess) -> str:
        """Classify a finished merge, rebase or cherry-pick."""
        # Unmerged paths decide first: `git checkout -m` exits 0 with conflicts.
        unmerged = self.git('diff', '--name-only', '--diff-filter=U').stdout.split()
        if unmerged:
            return SOURCE_CONFLICT if any(not p.startswith('.semantic/') for p in unmerged) else METADATA_ONLY
        if result.returncode != 0:
            return OTHER_STOP
        root = self.root
        if not self.git('diff', '--cached', '--name-only').stdout.split():
            # Committed: judge HEAD itself, not leftovers in the work tree.
            root = Path(tempfile.mkdtemp(prefix='aigit-head-')) / 'head'
            self.git('worktree', 'add', '-q', '--detach', str(root), 'HEAD')
        on_disk = tuple((root / '.semantic' / name).read_text(encoding='utf-8') for name in ARTIFACTS)
        fresh = on_disk == render_manifest(*build_manifest(root))
        if root != self.root:
            self.git('worktree', 'remove', '--force', str(root))
        return FRESH if fresh else STALE

    def abort(self) -> None:
        for command in (('merge', '--abort'), ('rebase', '--abort'), ('cherry-pick', '--abort')):
            self.git(*command)
        self.git('reset', '-q', '--hard')

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def snapshot_of_this_repository(dest: Path) -> None:
    """A clean copy of this repository at HEAD, as a realistic corpus.

    The package directory is renamed so `python -m aigit` inside the copy
    still runs the code under test.
    """
    archive = subprocess.run(['git', 'archive', 'HEAD'], cwd=REPO_ROOT, capture_output=True, check=True).stdout
    subprocess.run(['tar', '-x', '-C', str(dest)], input=archive, check=True)
    os.rename(dest / 'aigit', dest / 'aigit_corpus')
    shutil.rmtree(dest / '.semantic', ignore_errors=True)
