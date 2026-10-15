"""How often does `git merge-file` disagree with what `git merge` actually does?

The driver must reproduce Git's merge of a contested file. `git merge-file`
diffs with Myers; the ort strategy behind merge, rebase and cherry-pick uses
histogram. This draws random three-way merges of small low-entropy files --
where the two algorithms are most likely to part -- and compares the two.

    python experiments/merge_driver/algorithms.py --trials 400 --seed 2 --out DIR
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from harness import environment

ALPHABET = ['{', '}', 'x', 'y', 'return', '']
AGREE = 'agree'
BOTH_CLEAN_DIFFERENT = 'both clean, different text'
MERGE_FILE_ONLY_CLEAN = 'merge-file clean, git conflicts'
GIT_ONLY_CLEAN = 'git clean, merge-file conflicts'


def merge_file(ours: bytes, base: bytes, theirs: bytes) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        for name, data in (('o', ours), ('b', base), ('t', theirs)):
            Path(tmp, name).write_bytes(data)
        result = subprocess.run(['git', 'merge-file', '-p', '--quiet', 'o', 'b', 't'], cwd=tmp, capture_output=True)
        return result.stdout if result.returncode == 0 else None


def git_merge(ours: bytes, base: bytes, theirs: bytes) -> bytes | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT')}
    env.update(GIT_AUTHOR_NAME='e', GIT_AUTHOR_EMAIL='e@e', GIT_COMMITTER_NAME='e', GIT_COMMITTER_EMAIL='e@e')
    with tempfile.TemporaryDirectory() as tmp:
        def git(*args: str, data: bytes = b'') -> str:
            return subprocess.run(['git', *args], cwd=tmp, env=env, input=data, capture_output=True).stdout.decode().strip()

        def commit(data: bytes, parent: str | None = None) -> str:
            blob = git('hash-object', '-w', '--stdin', data=data)
            tree = git('mktree', data=f'100644 blob {blob}\tf\n'.encode())
            return git('commit-tree', tree, *(['-p', parent] if parent else []), '-m', 'x')

        git('init', '-q', '--template=')
        base_commit = commit(base)
        ours_commit, theirs_commit = commit(ours, base_commit), commit(theirs, base_commit)
        git('checkout', '-q', ours_commit)
        if subprocess.run(['git', 'merge', '-q', '--no-commit', '--no-ff', theirs_commit],
                          cwd=tmp, env=env, capture_output=True).returncode:
            return None
        return subprocess.run(['git', 'show', ':f'], cwd=tmp, env=env, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=400)
    parser.add_argument('--seed', type=int, default=2)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    def mutate(lines: list[str]) -> list[str]:
        lines = list(lines)
        for _ in range(rng.randint(1, 3)):
            at = rng.randrange(len(lines) + 1)
            if rng.random() < 0.5:
                lines.insert(at, rng.choice(ALPHABET))
            elif lines:
                lines.pop(min(at, len(lines) - 1))
        return lines

    def encode(lines: list[str]) -> bytes:
        return ('\n'.join(lines) + '\n').encode()

    rows = []
    for trial in range(args.trials):
        base = [rng.choice(ALPHABET) for _ in range(rng.randint(4, 12))]
        ours, theirs = mutate(base), mutate(base)
        by_merge_file = merge_file(encode(ours), encode(base), encode(theirs))
        by_git = git_merge(encode(ours), encode(base), encode(theirs))
        if by_merge_file == by_git:
            verdict = AGREE
        elif by_merge_file is not None and by_git is not None:
            verdict = BOTH_CLEAN_DIFFERENT
        elif by_merge_file is not None:
            verdict = MERGE_FILE_ONLY_CLEAN
        else:
            verdict = GIT_ONLY_CLEAN
        rows.append({'trial': trial, 'verdict': verdict,
                     'base': encode(base).decode(), 'ours': encode(ours).decode(), 'theirs': encode(theirs).decode()})

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / 'algorithms.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(Counter(r['verdict'] for r in rows))
    meta = {'experiment': 'algorithms', 'trials': args.trials, 'seed': args.seed, **environment(), 'summary': summary}
    (args.out / 'algorithms.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
