"""Corner-case sweep: thirty Git operations, each through real Git with the driver.

Each scenario builds a small history and runs one Git operation. A correct
tool merges fresh, stops on a genuine source conflict, or -- where Git cannot
be followed or the inputs are already wrong -- declines with a conflict that
asks for `aigit chunk`. A stale result is never acceptable.

    python experiments/merge_driver/sweep.py --out DIR
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from harness import FRESH, METADATA_ONLY, OTHER_STOP, SOURCE_CONFLICT, Repo, environment

A = 'def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n'
SCENARIOS = {}


def scenario(command: str, description: str, expected: str = FRESH):
    def register(function):
        SCENARIOS[function.__name__] = (function, command, description, expected)
        return function
    return register


STOP = 'stop'  # declines with a conflict asking for `aigit chunk`


def diverge(r: Repo, path: str = 'm.py', ours: str | None = None, theirs: str | None = None) -> None:
    r.commit({path: A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({path: theirs or '# top\n' + A}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({path: ours or A + '\n\ndef d():\n    return 4\n'}, 'main')


@scenario('git merge', 'Same file edited on both sides')
def plain_merge(r):
    diverge(r)
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge --squash', 'Squash merge')
def squash_merge(r):
    diverge(r)
    return r.git('merge', '--squash', 'feature')


@scenario('git merge b1 b2', 'Three heads in one merge (octopus)', STOP)
def octopus(r):
    r.commit({'m.py': A}, 'base')
    for name, edit in (('b1', lambda t: '# one\n' + t), ('b2', lambda t: t.replace('def c', '# two\ndef c'))):
        r.git('checkout', '-qb', name, 'main')
        r.commit({'m.py': edit(A)}, name)
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '\n\ndef d():\n    return 4\n'}, 'main')
    return r.git('merge', '--no-edit', 'b1', 'b2')


@scenario('git merge', 'Two merge bases (criss-cross history)')
def criss_cross(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'x')
    r.commit({'m.py': '# x\n' + A}, 'x1')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'm1')
    r.git('checkout', '-q', 'x')
    r.git('merge', '--no-edit', 'main')
    r.chunk()
    r.git('commit', '-qam', 'refresh', '--allow-empty')
    r.git('checkout', '-q', 'main')
    r.git('merge', '--no-edit', 'x~1')
    r.chunk()
    r.git('commit', '-qam', 'refresh', '--allow-empty')
    r.git('checkout', '-q', 'x')
    r.commit({'m.py': (r.root / 'm.py').read_text().replace('def b', '# xb\ndef b')}, 'x2')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': (r.root / 'm.py').read_text().replace('def c', '# mc\ndef c')}, 'm2')
    return r.git('merge', '--no-edit', 'x')


@scenario('git merge', 'Both branches adopted AIGit separately')
def first_adoption(r):
    r.commit({'m.py': A}, 'before AIGit', chunk=False)
    r.git('rm', '-rq', '--cached', '.semantic')
    shutil.rmtree(r.root / '.semantic', ignore_errors=True)
    r.git('commit', '-qm', 'no artifacts', '--allow-empty')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# top\n' + A}, 'feature adopts')
    r.git('checkout', '-q', 'main')
    shutil.rmtree(r.root / '.semantic', ignore_errors=True)
    r.commit({'m.py': A + '# main\n', 'other.py': A}, 'main adopts')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', "Other branch's artifacts already stale", STOP)
def theirs_stale(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# top\n' + A}, 'feature')
    r.commit({'m.py': '# top\n# unchunked\n' + A}, 'stale', chunk=False)
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', "This branch's artifacts already stale", STOP)
def ours_stale(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# top\n' + A}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    r.commit({'m.py': A + '# main\n# unchunked\n'}, 'stale', chunk=False)
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Symlink to a file both sides edit')
def symlink(r):
    r.commit({'target.py': A}, 'base')
    os.symlink('target.py', r.root / 'link.py')
    r.commit({}, 'link')
    r.git('checkout', '-qb', 'feature')
    r.commit({'target.py': '# top\n' + A}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({'target.py': A + '# main\n'}, 'main')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Source file that is not UTF-8')
def latin1_file(r):
    encode = lambda text: text.encode('latin-1')
    r.commit({'m.py': encode('# café\n' + A)}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': encode('# café\n# top\n' + A)}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': encode('# café\n' + A + '# main\n')}, 'main')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Edit vs rename of a path with spaces and accents')
def odd_path_rename(r):
    old, new = 'dir with space/ñ ü.py', 'dir with space/renamed ñ.py'
    r.commit({old: A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.git('mv', old, new)
    r.commit({}, 'rename')
    r.git('checkout', '-q', 'main')
    r.commit({old: A + '# main\n'}, 'edit')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Edit vs rename to a type outside the layer (.png)')
def renamed_out_of_layer(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.git('mv', 'm.py', 'm.png')
    r.commit({}, 'to png')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'edit')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Both sides rename one file differently', SOURCE_CONFLICT)
def rename_both_sides(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.git('mv', 'm.py', 'x.py')
    r.commit({}, 'x')
    r.git('checkout', '-q', 'main')
    r.git('mv', 'm.py', 'y.py')
    r.commit({}, 'y')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', '.semantic/ deleted on one side', STOP)
def semantic_deleted(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.git('rm', '-rq', '.semantic')
    r.git('commit', '-qm', 'drop artifacts')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Merge result no longer parses')
def merge_makes_syntax_error(r):
    diverge(r, theirs=A.replace('def a():', 'def a(:'))
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Empty file filled on one side')
def empty_file(r):
    r.commit({'e.py': '', 'm.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'e.py': 'x = 1\n'}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '#\n'}, 'main')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', '100 files edited on both sides')
def many_contested_files(r):
    count = 100
    r.commit({f'f{i}.py': A for i in range(count)}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({f'f{i}.py': '# top\n' + A for i in range(count)}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({f'f{i}.py': A + '# main\n' for i in range(count)}, 'main')
    return r.git('merge', '--no-edit', 'feature')


@scenario('git merge', 'Merge run from a subdirectory')
def from_subdirectory(r):
    r.commit({'sub/keep.py': A}, 'sub')
    diverge(r)
    return r.git('merge', '--no-edit', 'feature', cwd=r.root / 'sub')


@scenario('git merge', 'Merge inside a linked worktree')
def linked_worktree(r):
    diverge(r)
    tree = Path(tempfile.mkdtemp(prefix='aigit-wt-')) / 'wt'
    r.git('worktree', 'add', '-q', '-b', 'wt', str(tree), 'main')
    result = r.git('merge', '--no-edit', 'feature', cwd=tree)
    r.root = tree
    return result


@scenario('git -c merge.renormalize=true merge', 'Option that changes how Git merges files', STOP)
def renormalize(r):
    diverge(r)
    return r.git('-c', 'merge.renormalize=true', 'merge', '--no-edit', 'feature')


@scenario('git rebase', 'Rebase a branch')
def rebase(r):
    diverge(r)
    r.git('checkout', '-q', 'feature')
    return r.git('rebase', 'main')


@scenario('git rebase -i', 'Reorder commits interactively')
def interactive_rebase(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# f1\n' + A}, 'f1')
    r.commit({'n.py': A}, 'f2')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    r.git('checkout', '-q', 'feature')
    reverse = "sh -c 'tac \"$1\" | grep -v \"^#\" | grep . > \"$1.n\"; mv \"$1.n\" \"$1\"' -"
    return r.git('-c', f'sequence.editor={reverse}', 'rebase', '-i', 'main')


@scenario('git rebase --rebase-merges', 'Rebase that replays a merge')
def rebase_merges(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# f\n' + A}, 'f')
    r.git('checkout', '-qb', 'side', 'main')
    r.commit({'n.py': A}, 'side')
    r.git('checkout', '-q', 'feature')
    r.git('merge', '--no-edit', 'side')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    r.git('checkout', '-q', 'feature')
    return r.git('rebase', '--rebase-merges', 'main')


@scenario('git rebase --onto', 'Transplant a branch')
def rebase_onto(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'old')
    r.commit({'o.py': A}, 'old')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# f\n' + A}, 'f')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    r.git('checkout', '-q', 'feature')
    return r.git('rebase', '--onto', 'main', 'old')


@scenario('git rebase --autostash', 'Rebase over uncommitted work')
def rebase_autostash(r):
    r.commit({'notes.md': '# notes\n'}, 'notes')
    diverge(r)
    r.git('checkout', '-q', 'feature')
    r.write({'notes.md': '# notes\nwip\n'})
    return r.git('rebase', '--autostash', 'main')


@scenario('git pull --rebase', 'Pull with rebase from a remote')
def pull_rebase(r):
    diverge(r)
    remote = Path(tempfile.mkdtemp(prefix='aigit-remote-')) / 'origin.git'
    subprocess.run(['git', 'clone', '-q', '--bare', str(r.root), str(remote)], check=True)
    r.git('remote', 'add', 'origin', str(remote))
    r.git('fetch', '-q', 'origin')
    r.git('checkout', '-q', 'feature')
    r.git('branch', '-q', '-u', 'origin/main')
    return r.git('pull', '--rebase')


@scenario('git cherry-pick', 'Cherry-pick one commit')
def cherry_pick(r):
    diverge(r)
    return r.git('cherry-pick', 'feature')


@scenario('git cherry-pick A..B', 'Cherry-pick a range')
def cherry_pick_range(r):
    r.commit({'m.py': A}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': '# one\n' + A}, 'f1')
    r.commit({'m.py': '# one\n' + A.replace('def c', '# two\ndef c')}, 'f2')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': A + '# main\n'}, 'main')
    return r.git('cherry-pick', 'main..feature')


@scenario('git cherry-pick', 'File stored with CRLF line endings')
def crlf_cherry_pick(r):
    crlf = lambda text: text.replace('\n', '\r\n').encode()
    r.commit({'m.py': crlf(A)}, 'base')
    r.git('checkout', '-qb', 'feature')
    r.commit({'m.py': crlf('# top\n' + A)}, 'feature')
    r.git('checkout', '-q', 'main')
    r.commit({'m.py': crlf(A + '# main\n')}, 'main')
    return r.git('cherry-pick', 'feature')


@scenario('git revert', 'Revert a commit older than HEAD')
def revert_older_commit(r):
    r.commit({'m.py': A}, 'base')
    r.commit({'m.py': A.replace('return 2', 'return 20')}, 'change b')
    r.commit({'m.py': '# later\n' + A.replace('return 2', 'return 20')}, 'later')
    return r.git('revert', '--no-edit', 'HEAD~1')


@scenario('git stash pop', 'Pop work stashed before a newer commit')
def stash_pop(r):
    r.commit({'m.py': A}, 'base')
    r.write({'m.py': '# wip\n' + A})
    r.chunk()
    r.git('stash', '-q')
    r.commit({'m.py': A + '\n\ndef d():\n    return 4\n'}, 'main')
    return r.git('stash', 'pop')


@scenario('git am -3', 'Apply an emailed patch')
def am_three_way(r):
    diverge(r)
    patch = Path(tempfile.mkdtemp(prefix='aigit-patch-')) / 'change.patch'
    patch.write_text(r.git('format-patch', '-1', 'feature', '--stdout').stdout, encoding='utf-8')
    return r.git('am', '-3', str(patch))


@scenario('git checkout -m', 'Switch branches carrying uncommitted work', STOP)
def checkout_merge(r):
    diverge(r)
    r.git('checkout', '-q', 'feature~1')
    r.write({'m.py': A + '# dirty\n'})
    r.chunk()
    return r.git('checkout', '-m', 'feature')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for name, (run, command, description, expected) in SCENARIOS.items():
        repo = Repo()
        started = time.perf_counter()
        result = run(repo)
        elapsed = time.perf_counter() - started
        outcome = repo.outcome(result)
        ok = outcome == expected or (expected == STOP and outcome in {METADATA_ONLY, OTHER_STOP})
        rows.append({'scenario': name, 'command': command, 'description': description, 'outcome': outcome,
                     'expected': expected, 'as_expected': int(ok), 'seconds': round(elapsed, 2)})
        print(f"{name:26} {outcome:14} {'ok' if ok else 'UNEXPECTED'}")
        repo.remove()
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / 'sweep.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    meta = {'experiment': 'sweep', 'scenarios': len(rows), **environment(),
            'as_expected': sum(row['as_expected'] for row in rows),
            'stale': sum(row['outcome'] == 'stale' for row in rows)}
    (args.out / 'sweep.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
