"""The crew simulation is executable documentation, so CI runs it.

If a gate regresses, this fails here rather than in someone's merge queue.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[1] / 'examples' / 'crew_sim' / 'run_crew.py'


@pytest.fixture(scope='module')
def simulation() -> str:
    proc = subprocess.run(
        [sys.executable, str(SIM)],
        text=True,
        capture_output=True,
        timeout=600,
        cwd=SIM.parents[2],
    )
    assert proc.returncode == 0, f'simulation reported failures:\n{proc.stdout}\n{proc.stderr}'
    return proc.stdout


def test_simulation_holds_every_property(simulation: str) -> None:
    assert 'ALL PROPERTIES HELD' in simulation
    assert 'FAILURES:' not in simulation


@pytest.mark.parametrize(
    'prop',
    [
        'delocalized_async_timeline',
        'strict_gate_blocks_broken_draft',
        'merge_queue_blocks_same_name_duplicate',
        'merge_queue_blocks_renamed_duplicate',
        'rename_lands_as_lineage',
        'unsigned_commit_rejected',
        'drift_gate_blocks_stale_state',
    ],
)
def test_property_is_reported(simulation: str, prop: str) -> None:
    line = next(ln for ln in simulation.splitlines() if ln.strip().startswith(prop))
    assert 'FAIL' not in line, line


def test_both_duplicate_gates_fire(simulation: str) -> None:
    """The two gates catch different things and both must be exercised: agents
    that picked the same name (add/add) and one that renamed (duplicate-work)."""
    assert 'BLOCKED (add/add)' in simulation
    assert 'BLOCKED (duplicate-work)' in simulation


def test_runs_without_network_or_model_weights(simulation: str) -> None:
    assert 'backend used: deterministic' in simulation
