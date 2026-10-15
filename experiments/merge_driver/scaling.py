"""Driver time against the number of files both sides changed.

Compares the batched ort merge (one throwaway repository for every contested
file) with the per-file variant it replaced (one throwaway repository each).

    python experiments/merge_driver/scaling.py --sizes 10,25,50,100,200 --repeats 3 --out DIR
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from harness import FRESH, REPO_ROOT, Repo, environment

A = 'def a():\n    return 1\n\n\ndef b():\n    return 2\n'

# A sitecustomize that swaps the batched merge for one merge per file, so the
# driver subprocess Git launches runs the variant being measured.
PER_FILE = '''
import aigit.core as core
_batched = core._merge_like_git
core._merge_like_git = lambda jobs: {key: _batched({key: job})[key] for key, job in jobs.items()}
'''


def run(count: int, variant: str, shim: Path) -> tuple[float, str]:
    repo = Repo()
    if variant == 'per-file':
        repo.env['PYTHONPATH'] = f'{shim}:{REPO_ROOT}'
    repo.commit({f'f{i}.py': A for i in range(count)}, 'base')
    repo.git('checkout', '-qb', 'feature')
    repo.commit({f'f{i}.py': '# top\n' + A for i in range(count)}, 'feature')
    repo.git('checkout', '-q', 'main')
    repo.commit({f'f{i}.py': A + '# main\n' for i in range(count)}, 'main')
    started = time.perf_counter()
    result = repo.git('merge', '--no-edit', 'feature')
    elapsed = time.perf_counter() - started
    outcome = repo.outcome(result)
    repo.remove()
    return elapsed, outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--sizes', default='10,25,50,100,200')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    shim = Path(Repo().root) / 'shim'
    shim.mkdir()
    (shim / 'sitecustomize.py').write_text(PER_FILE, encoding='utf-8')

    rows = []
    for count in (int(size) for size in args.sizes.split(',')):
        for variant in ('per-file', 'batched'):
            times = []
            for _ in range(args.repeats):
                elapsed, outcome = run(count, variant, shim)
                assert outcome == FRESH, f'{variant} at {count} files: {outcome}'
                times.append(elapsed)
            rows.append({'files': count, 'variant': variant, 'median_seconds': round(statistics.median(times), 3),
                         'min_seconds': round(min(times), 3), 'max_seconds': round(max(times), 3)})
            print(rows[-1])
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / 'scaling.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    meta = {'experiment': 'scaling', 'repeats': args.repeats, **environment()}
    (args.out / 'scaling.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
