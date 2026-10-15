"""Replay concurrent changes through real Git, with and without the driver.

Each trial branches A and B off a snapshot of this repository; each side makes
one random change (insert or edit a line, add, delete or rename a file),
half of the time to the same file. The two are then combined by git merge,
git rebase and git cherry-pick, once with Git's line-based text merge for the
artifacts and once with the AIGit driver.

    python experiments/merge_driver/replay.py --trials 150 --seed 4 --out DIR
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import tempfile
from collections import Counter
from pathlib import Path

from harness import OUTCOMES, Repo, environment, snapshot_of_this_repository
from aigit.core import iter_repo_files

MODES = ('merge', 'rebase', 'cherry-pick')
METHODS = ('text', 'driver')
OPERATIONS = ('insert', 'insert', 'edit', 'add', 'delete', 'rename')


def change(repo: Repo, path: str, tag: str, rng: random.Random) -> str:
    target = repo.root / path
    if not target.exists():
        return 'none'
    operation = rng.choice(OPERATIONS)
    lines = target.read_text(encoding='utf-8').split('\n')
    if operation == 'insert':
        lines.insert(rng.randrange(1, max(2, len(lines))), f'# {tag}')
        target.write_text('\n'.join(lines), encoding='utf-8')
    elif operation == 'edit':
        index = rng.randrange(len(lines))
        lines[index] += f'  # {tag}'
        target.write_text('\n'.join(lines), encoding='utf-8')
    elif operation == 'add':
        (repo.root / f'new_{tag}.py').write_text(f'def fn_{tag}():\n    return 1\n', encoding='utf-8')
    elif operation == 'delete':
        repo.git('rm', '-q', path)
    else:
        repo.git('mv', path, str(Path(path).with_name('renamed_' + Path(path).name)))
    return operation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=150)
    parser.add_argument('--seed', type=int, default=4)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    root = Path(tempfile.mkdtemp(prefix='aigit-replay-'))
    snapshot_of_this_repository(root)
    repo = Repo(root)
    repo.commit(message='base')
    files = [str(p) for p in iter_repo_files(root) if p.suffix in {'.py', '.md'}]

    rows = []
    for trial in range(args.trials):
        file_a = rng.choice(files)
        file_b = file_a if rng.random() < 0.5 else rng.choice(files)
        repo.git('checkout', '-qB', 'A', 'main')
        op_a = change(repo, file_a, f'A{trial}', rng)
        repo.commit(message='A')
        repo.git('checkout', '-qB', 'B', 'main')
        op_b = change(repo, file_b, f'B{trial}', rng)
        repo.commit(message='B')
        for mode in MODES:
            for method in METHODS:
                repo.install_driver() if method == 'driver' else repo.uninstall_driver()
                repo.git('checkout', '-qB', 'W', 'A')
                if mode == 'merge':
                    result = repo.git('merge', '--no-edit', 'B')
                elif mode == 'rebase':
                    result = repo.git('rebase', 'B')
                else:
                    result = repo.git('cherry-pick', 'B')
                rows.append({
                    'trial': trial, 'mode': mode, 'method': method,
                    'same_file': int(file_a == file_b), 'change_a': op_a, 'change_b': op_b,
                    'outcome': repo.outcome(result),
                })
                repo.abort()
        repo.git('checkout', '-q', 'main')
    repo.remove()

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / 'replay.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        f'{mode}/{method}': {o: Counter(r['outcome'] for r in rows if r['mode'] == mode and r['method'] == method)[o]
                             for o in OUTCOMES}
        for mode in MODES for method in METHODS
    }
    meta = {'experiment': 'replay', 'trials': args.trials, 'seed': args.seed, **environment(), 'summary': summary}
    (args.out / 'replay.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
