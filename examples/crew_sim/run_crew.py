#!/usr/bin/env python3
"""Simulate a delocalized async agent crew against AIGit's semantic gates.

Six agents in six timezones, each on its own branch, land work through a trunk
merge queue. The point is not that agents can write code -- it is that the
gates behave correctly when they write it *concurrently and imperfectly*:

    P0  agents act at different UTC instants, interleaved, never synchronized
    P1  a broken draft is caught before it reaches a branch (chunk --strict)
    P2  the merge queue blocks duplicate work, whether the duplicate shares a
        name (add/add) or hides behind a different one (duplicate-work)
    P3  a rename lands as lineage, not delete + add
    P4  a signed commit verifies, and an unsigned one is rejected when a
        signature is required
    P5  a commit that forgot to re-chunk is caught by the freshness gate

Run deterministically (the default -- no network, no weights):

    python examples/crew_sim/run_crew.py

Run against a real model:

    AIGIT_CREW_ENDPOINT=https://api.openai.com/v1 AIGIT_CREW_MODEL=gpt-4o-mini \
    AIGIT_CREW_API_KEY=sk-... python examples/crew_sim/run_crew.py

    AIGIT_CREW_LOCAL=1 AIGIT_CREW_MODEL=LiquidAI/LFM2-1.2B \
    python examples/crew_sim/run_crew.py
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import select_backend  # noqa: E402

from aigit import core  # noqa: E402

# --------------------------------------------------------------------------- #
# the crew: one agent per timezone, acting at its own local working hour
# --------------------------------------------------------------------------- #
AGENTS = {
    'aria': {'tz': 'Lisbon', 'utc_offset': 0, 'local_hour': 9},
    'ravi': {'tz': 'Bengaluru', 'utc_offset': 5, 'local_hour': 14},
    'lin': {'tz': 'Shanghai', 'utc_offset': 8, 'local_hour': 21},
    'bruno': {'tz': 'Sao_Paulo', 'utc_offset': -3, 'local_hour': 10},
    'dana': {'tz': 'San_Francisco', 'utc_offset': -7, 'local_hour': 16},
    'kai': {'tz': 'Berlin', 'utc_offset': 1, 'local_hour': 18},
}

TASKS = {
    'route': {
        'file': 'agentmesh/router.py',
        'func': 'route',
        'params': 'request',
        'spec': "pick a downstream handler via registry_lookup(request['intent'])",
    },
    'allow_request': {
        'file': 'agentmesh/ratelimit.py',
        'func': 'allow_request',
        'params': 'bucket, cost=1',
        'spec': 'token-bucket admission: refill, then allow when tokens >= cost',
    },
    'register_tool': {
        'file': 'agentmesh/tools.py',
        'func': 'register_tool',
        'params': 'name, handler',
        'spec': 'register handler in _TOOLS, rejecting duplicate names',
    },
    'pick_provider': {
        'file': 'agentmesh/providers.py',
        'func': 'pick_provider',
        'params': 'model',
        'spec': "return the first provider in _PROVIDERS offering model, else 'fallback'",
    },
}

SEED_FILES = {
    'agentmesh/__init__.py': '"""A tiny agent mesh, used as the crew\'s codebase."""\n',
    'agentmesh/registry.py': (
        '_HANDLERS = {}\n\n\n'
        'def registry_lookup(intent):\n'
        '    return _HANDLERS.get(intent)\n'
    ),
    'agentmesh/router.py': 'from agentmesh.registry import registry_lookup\n',
    'agentmesh/ratelimit.py': '_DEFAULT_CAPACITY = 100\n',
    'agentmesh/tools.py': '_TOOLS = {}\n',
    'agentmesh/providers.py': (
        '_PROVIDERS = [\n'
        "    {'name': 'openai', 'models': ['gpt-4o'], 'cost': 3, 'latency_ms': 400},\n"
        "    {'name': 'local', 'models': ['lfm2'], 'cost': 0, 'latency_ms': 90},\n"
        ']\n'
    ),
}


#: HMAC key the simulated organisation signs provenance with
SIGNING_KEY = 'crew-simulation-signing-key'


def banner(title: str) -> None:
    print('\n' + '=' * 72 + f'\n{title}\n' + '=' * 72)


class Repo:
    """A throwaway git repo plus the aigit CLI, scoped to one simulation."""

    def __init__(self, root: Path):
        self.root = root

    def git(self, *args: str) -> str:
        return subprocess.run(
            ['git', *args], cwd=self.root, check=True, text=True, capture_output=True
        ).stdout.strip()

    def aigit(self, *args: str, sign: bool = True) -> tuple[int, str]:
        env = {
            **os.environ,
            'PYTHONPATH': str(Path(__file__).resolve().parents[2]),
            'AIGIT_PROVENANCE_KEY': SIGNING_KEY,
        }
        if not sign:
            # an agent that never had the key: its rows go in unsigned
            env.pop('AIGIT_PROVENANCE_KEY')
        proc = subprocess.run(
            [sys.executable, '-m', 'aigit.cli', *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            env=env,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def aigit_ok(self, *args: str, sign: bool = True) -> str:
        """Run a command that must succeed; a silent failure here would make a
        downstream assertion pass for the wrong reason."""
        code, output = self.aigit(*args, sign=sign)
        if code != 0:
            raise RuntimeError(f'aigit {" ".join(args)} failed ({code}):\n{output}')
        return output

    def chunk(self) -> None:
        self.aigit('chunk', '--repo', '.')

    def commit(self, message: str) -> str:
        self.git('add', '-A')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def seed(self) -> str:
        self.git('init', '-q', '.')
        self.git('config', 'user.email', 'crew@agentmesh.test')
        self.git('config', 'user.name', 'agentmesh crew')
        self.git('checkout', '-q', '-b', 'trunk')
        for rel, text in SEED_FILES.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        self.chunk()
        return self.commit('seed: agentmesh skeleton')


def strict_gate_rejects(repo: Repo, path: str) -> tuple[bool, str]:
    """Run the real freshness/strict gate over the working tree.

    ``chunk --strict`` exits non-zero when a file cannot be parsed. A rejected
    draft is rolled back so the agent's next attempt starts from a clean tree,
    and the artifacts are rebuilt either way.
    """
    code, output = repo.aigit('chunk', '--repo', '.', '--strict')
    if code == 0:
        return False, ''
    reason = next(
        (line.strip() for line in output.splitlines() if 'strict:' in line), output.strip()
    )
    repo.git('checkout', '--', path)
    repo.aigit('chunk', '--repo', '.')
    return True, reason


def append_function(repo: Repo, task: dict, code: str) -> None:
    path = repo.root / task['file']
    path.write_text(path.read_text(encoding='utf-8') + '\n\n' + code, encoding='utf-8')


def agent_branch(
    repo: Repo,
    backend,
    agent: str,
    task_id: str,
    variant: str,
    trunk: str,
    func_override: str | None = None,
    broken_first: bool = False,
) -> tuple[str, bool, str, str]:
    """One agent: draft, gate the draft, then publish a branch.

    Returns ``(branch, accepted, note, feature_sha)``. A draft that fails the strict gate is
    never committed -- the agent retries, exactly as a CI-gated crew would.
    """
    task = dict(TASKS[task_id], impl_key=TASKS[task_id]['func'])
    if func_override:
        task['func'] = func_override
    branch = f'feat/{task["func"]}-{agent}'
    repo.git('checkout', '-q', trunk)
    repo.git('checkout', '-q', '-b', branch)

    attempts = 0
    for candidate_variant in (['broken'] if broken_first else []) + [variant]:
        attempts += 1
        code = backend.write_function(task, candidate_variant)
        append_function(repo, task, code)
        # Put the draft in front of the real gate rather than judging it here:
        # a harness-side ast.parse would report this property green even if
        # `chunk --strict` stopped rejecting anything.
        rejected, reason = strict_gate_rejects(repo, task['file'])
        if rejected:
            print(f'      strict gate rejected {agent}\'s draft: {reason}')
            continue  # agent retries rather than committing it
        head = attest(
            repo,
            agent=agent,
            model=getattr(backend, 'name', 'unknown'),
            prompt=f'{agent}:{task_id}:{candidate_variant}',
            message=f'feat({agent}): {task["func"]}',
        )
        return branch, True, f'branch ready (attempts={attempts}, {head[:9]})', head
    return branch, False, f'no parseable draft after {attempts} attempts', ''


def attest(repo: Repo, agent: str, model: str, prompt: str, message: str, sign: bool = True) -> str:
    """Commit staged work as an attested change, and return its sha.

    ``verify-provenance`` needs both halves and checks they agree: an
    ``AI-Provenance`` trailer on the commit, and a log row for that same sha
    whose prompt hash the trailer prefixes. The row can only be written once the
    commit exists, so it lands in a follow-up commit -- which also puts it on the
    branch, where a merge can carry it to trunk.
    """
    repo.git('add', '-A')
    repo.aigit_ok(
        'commit', '-m', message, '--agent', agent, '--model', model, '--prompt', prompt
    )
    head = repo.git('rev-parse', 'HEAD')
    repo.aigit_ok(
        'record-provenance', '--agent', agent, '--model', model, '--prompt', prompt, sign=sign
    )
    repo.git('add', '.semantic')
    repo.git('commit', '-qm', f'chore({agent}): record provenance for {head[:9]}')
    return head


@contextlib.contextmanager
def chdir(path: Path):
    """aigit's manifest readers shell out to git in the process cwd."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def merge_queue(repo: Repo, trunk: str, branches: list[tuple[str, str, str]]) -> list[dict]:
    """Land branches one at a time, gating each against the current trunk.

    Uses the `semantic-merge` CLI rather than the library, because that is the
    surface a real merge queue calls.
    """
    results = []
    for agent, task_id, branch in branches:
        base = repo.git('merge-base', trunk, branch)
        report = repo.root / 'merge-report.json'
        repo.aigit(
            'semantic-merge', '--base', base, '--ours', trunk,
            '--theirs', branch, '--output', str(report),
        )
        conflicts = json.loads(report.read_text(encoding='utf-8'))['conflicts']
        report.unlink(missing_ok=True)
        if conflicts:
            kinds = ', '.join(sorted({c['kind'] for c in conflicts}))
            results.append(
                {'agent': agent, 'task': task_id, 'integrated': False,
                 'kinds': kinds, 'conflicts': conflicts}
            )
            continue
        repo.git('checkout', '-q', trunk)
        landed, detail = land(repo, branch)
        results.append(
            {'agent': agent, 'task': task_id, 'integrated': landed,
             'kinds': '' if landed else detail}
        )
    return results


def _union_jsonl(ours: str, theirs: str) -> str:
    """Merge two append-only JSONL logs, keeping every distinct row once."""
    seen: dict[str, None] = {}
    for side in (ours, theirs):
        for line in side.splitlines():
            if line.strip():
                seen.setdefault(line, None)
    return ''.join(f'{line}\n' for line in seen)


def land(repo: Repo, branch: str) -> tuple[bool, str]:
    """Merge a branch that already cleared the semantic gate.

    Every branch regenerates ``.semantic/``, so concurrent branches always
    collide *textually* there even when their code does not. Derived artifacts
    are rebuilt, never merged: resolve them by re-running the chunker. A
    conflict anywhere else is a real one and stops the queue.
    """
    merge = subprocess.run(
        ['git', 'merge', '--no-edit', branch],
        cwd=repo.root, text=True, capture_output=True,
    )
    if merge.returncode == 0:
        return True, ''
    conflicted = [
        line for line in repo.git('diff', '--name-only', '--diff-filter=U').splitlines() if line
    ]
    outside = [path for path in conflicted if not path.startswith('.semantic/')]
    if outside:
        repo.git('merge', '--abort')
        return False, f'textual conflict in {", ".join(outside)}'
    for path in conflicted:
        if path.endswith('provenance.jsonl'):
            # An append-only attestation log, not a derived file: taking one
            # side would silently drop the other branch's provenance.
            union = _union_jsonl(
                repo.git('show', f':2:{path}'), repo.git('show', f':3:{path}')
            )
            (repo.root / path).write_text(union, encoding='utf-8')
        else:
            repo.git('checkout', '--ours', '--', path)
    repo.git('add', '.semantic')
    repo.git('commit', '-q', '--no-edit')
    repo.chunk()
    if repo.git('status', '--porcelain'):
        repo.commit(f'chore: re-chunk after merging {branch}')
    return True, ''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', metavar='DIR', help='keep the simulated repo at DIR')
    args = parser.parse_args()

    backend, how = select_backend()
    scores: dict[str, str] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(args.keep) if args.keep else Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        repo = Repo(root)

        banner('AGENTMESH CREW SIMULATION')
        print(f'backend: {getattr(backend, "name", "?")}  ({how})')
        trunk_seed = repo.seed()
        print(f'seed trunk @ {trunk_seed[:9]} in {root}')

        # ---- P0 delocalized schedule ---------------------------------------
        banner('P0  Delocalized asynchronous schedule (ordered by UTC instant)')
        plan = [
            ('aria', 'route', 'default', None, False),
            ('ravi', 'allow_request', 'default', None, True),
            ('lin', 'register_tool', 'default', None, False),
            ('bruno', 'pick_provider', 'cost_first', None, False),
            ('dana', 'pick_provider', 'latency_first', None, False),
            # kai solves bruno's ticket under a different name
            ('kai', 'pick_provider', 'renamed', 'choose_provider', False),
        ]
        timeline = sorted(
            (
                (AGENTS[a]['local_hour'] - AGENTS[a]['utc_offset']) % 24,
                a, task_id, variant, override, broken,
            )
            for a, task_id, variant, override, broken in plan
        )
        for utc, agent, task_id, _v, _o, _b in timeline:
            meta = AGENTS[agent]
            print(
                f'  {utc:02d}:00 UTC  ({meta["local_hour"]:02d}:00 {meta["tz"]:<14})'
                f'  {agent:<6} -> {task_id}'
            )
        distinct = len({a for _u, a, *_ in timeline})
        scores['delocalized_async_timeline'] = (
            f'PASS ({distinct} agents across {len({AGENTS[a]["tz"] for _u, a, *_ in timeline})} timezones)'
        )

        # ---- P1 fan-out under the strict gate ------------------------------
        banner('P1  Async fan-out  (strict draft gate + signed provenance)')
        branches: list[tuple[str, str, str]] = []
        feature_shas: dict[tuple[str, str], str] = {}
        notes: list[str] = []
        for _utc, agent, task_id, variant, override, broken in timeline:
            branch, ok, note, sha = agent_branch(
                repo, backend, agent, task_id, variant, trunk_seed,
                func_override=override, broken_first=broken,
            )
            notes.append(note)
            print(f'  {agent:<6} {task_id:<14} -> {"ACCEPTED" if ok else "REJECTED"}  ({note})')
            if ok:
                branches.append((agent, task_id, branch))
                feature_shas[(agent, task_id)] = sha
        retried = [n for n in notes if 'attempts=2' in n]
        scores['strict_gate_blocks_broken_draft'] = (
            f'PASS (chunk --strict rejected {len(retried)} draft(s) before commit)'
            if retried
            else 'n/a this run (every draft parsed; gate exercised by tests/test_chunk_gates.py)'
        )

        # ---- P2 merge queue -------------------------------------------------
        banner('P2  Trunk merge queue  (add/add and duplicate-work gates)')
        repo.git('checkout', '-q', 'trunk')
        results = merge_queue(repo, 'trunk', branches)
        for row in results:
            verdict = 'INTEGRATED' if row['integrated'] else f'BLOCKED ({row["kinds"]})'
            print(f'  {row["agent"]:<6} {row["task"]:<14} -> {verdict}')
        integrated_shas = [
            feature_shas[(row['agent'], row['task'])]
            for row in results
            if row['integrated'] and (row['agent'], row['task']) in feature_shas
        ]
        blocked_kinds = {k for row in results if not row['integrated']
                         for k in row['kinds'].split(', ') if k}
        for kind, key in (('add/add', 'merge_queue_blocks_same_name_duplicate'),
                          ('duplicate-work', 'merge_queue_blocks_renamed_duplicate')):
            if kind in blocked_kinds:
                scores[key] = f'PASS ({kind} blocked at the queue)'
            else:
                scores[key] = f'FAIL ({kind} not raised)'
                failures.append(key)

        # ---- P2b reimplementation of code already on trunk -------------------
        banner('P2b  A newcomer reimplements code that is already on trunk')
        trunk_head = repo.git('rev-parse', 'trunk')
        repo.git('checkout', '-q', '-b', 'feat/newcomer-route')
        router = repo.root / 'agentmesh/router.py'
        existing = router.read_text(encoding='utf-8')
        # An agent that never read router.py writes the same behaviour again,
        # under its own name. Nobody else is working on it -- there is no
        # concurrent addition to collide with, only the code already there.
        after_signature = existing.split('def route(', 1)[1]
        router.write_text(
            f'{existing}\n\ndef dispatch({after_signature}', encoding='utf-8'
        )
        repo.chunk()
        attest(repo, agent='newcomer', model='deterministic',
               prompt='newcomer:dispatch', message='feat(newcomer): dispatch')
        report = repo.root / 'newcomer-merge.json'
        repo.aigit_ok('semantic-merge', '--base', trunk_head, '--ours', 'trunk',
                      '--theirs', 'feat/newcomer-route', '--output', str(report))
        conflicts = json.loads(report.read_text(encoding='utf-8'))['conflicts']
        report.unlink(missing_ok=True)
        existing_scope = [c for c in conflicts if c.get('scope') == 'existing']
        if existing_scope:
            c = existing_scope[0]
            print(f'  BLOCKED: {c["anchor"]} reimplements {c["theirs_anchor"]} '
                  f'(similarity {c["similarity"]})')
            scores['queue_blocks_reimplementation_of_existing_code'] = (
                'PASS (duplicate-work/existing blocked the newcomer)'
            )
        else:
            scores['queue_blocks_reimplementation_of_existing_code'] = (
                'FAIL (reimplementation of existing code merged clean)'
            )
            failures.append('queue_blocks_reimplementation_of_existing_code')
        repo.git('checkout', '-q', 'trunk')

        # ---- P3 lineage on rename ------------------------------------------
        banner('P3  Refactor lineage  (rename must not read as delete + add)')
        before = repo.git('rev-parse', 'HEAD')
        repo.git('checkout', '-q', '-b', 'refactor/registry-rename')
        registry = repo.root / 'agentmesh/registry.py'
        registry.write_text(
            registry.read_text(encoding='utf-8').replace(
                'def registry_lookup(', 'def lookup_handler('
            ),
            encoding='utf-8',
        )
        repo.chunk()
        repo.commit('refactor(kai): registry_lookup -> lookup_handler')
        with chdir(repo.root):
            diff = core.compute_semantic_diff(
                core._read_manifest_from_ref(before),
                core._read_manifest_from_ref('refactor/registry-rename'),
            )
        lineage = [
            edge for edge in diff['lineage']
            if 'registry_lookup' in json.dumps(edge) and 'lookup_handler' in json.dumps(edge)
        ]
        if lineage:
            print(f'  lineage recovered: {json.dumps(lineage[0])}')
            scores['rename_lands_as_lineage'] = 'PASS (rename paired, not delete+add)'
        else:
            scores['rename_lands_as_lineage'] = 'FAIL (rename split into delete + add)'
            failures.append('rename_lands_as_lineage')
        repo.git('checkout', '-q', 'trunk')

        # ---- P4 provenance --------------------------------------------------
        banner('P4  Supply chain  (a signed commit vs an unsigned one)')
        # An agent's own commit, attested and signed, that reached trunk.
        signed_sha = integrated_shas[0]
        code, output = repo.aigit('verify-provenance', '--ref', signed_sha, '--require-signature')
        signed_ok = code == 0 and json.loads(output.splitlines()[-1]).get('signed') is True
        print(f'  signed agent commit {signed_sha[:9]}: '
              f'{"VERIFIED" if signed_ok else "FAILED -> " + output.strip()}')
        if signed_ok:
            scores['signed_commit_verifies'] = 'PASS (attested commit verifies under --require-signature)'
        else:
            scores['signed_commit_verifies'] = 'FAIL (a legitimately signed commit did not verify)'
            failures.append('signed_commit_verifies')

        # An intruder who can write commits and provenance rows but lacks the
        # signing key. Giving it a valid trailer and a log row isolates the
        # *signature* gate -- a commit with no trailer at all would be rejected
        # by the earlier checks, and would prove nothing about signing.
        (repo.root / 'agentmesh/backdoor.py').write_text(
            'def exfiltrate(secrets):\n    return secrets\n', encoding='utf-8'
        )
        repo.chunk()
        forged = attest(
            repo, agent='mallory', model='unknown',
            prompt='mallory:backdoor', message='feat: harmless cleanup', sign=False,
        )
        unsigned_code, _ = repo.aigit('verify-provenance', '--ref', forged)
        gated_code, _ = repo.aigit('verify-provenance', '--ref', forged, '--require-signature')
        if unsigned_code == 0 and gated_code != 0:
            print(f'  unsigned commit {forged[:9]}: passes plain verify, REJECTED when a '
                  'signature is required')
            scores['unsigned_commit_rejected'] = 'PASS (signature gate rejects the unsigned commit)'
        else:
            scores['unsigned_commit_rejected'] = (
                f'FAIL (plain verify={unsigned_code}, --require-signature={gated_code}; '
                'expected 0 then non-zero)'
            )
            failures.append('unsigned_commit_rejected')

        # ---- P5 drift gate ---------------------------------------------------
        banner('P5  CI drift gate  (an agent forgets to re-chunk)')
        (repo.root / 'agentmesh/tools.py').write_text(
            (repo.root / 'agentmesh/tools.py').read_text(encoding='utf-8')
            + '\n\ndef unregister_tool(name):\n    return _TOOLS.pop(name, None)\n',
            encoding='utf-8',
        )
        repo.commit('feat(dana): unregister_tool (forgot to re-chunk)')
        rc, _out = repo.aigit('chunk', '--repo', '.', '--check')
        if rc != 0:
            print('  chunk --check on un-chunked commit: STALE (blocked)')
            scores['drift_gate_blocks_stale_state'] = 'PASS (stale semantic state blocked)'
        else:
            scores['drift_gate_blocks_stale_state'] = 'FAIL (stale state passed the gate)'
            failures.append('drift_gate_blocks_stale_state')

        # ---- scorecard --------------------------------------------------------
        banner('SCORECARD')
        for name, verdict in scores.items():
            print(f'  {name:<38} {verdict}')
        print()
        if failures:
            print('FAILURES: ' + ', '.join(failures))
        else:
            print('ALL PROPERTIES HELD')
        print(f'backend used: {getattr(backend, "name", "?")} '
              f'(real={getattr(backend, "real", False)})')
        if args.keep:
            print(f'simulated repo kept at {root}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
