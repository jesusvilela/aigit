"""The committed merge-driver figures must be exactly what the committed data renders."""
import importlib.util
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / 'docs' / 'evals' / 'results' / '2026-10-15-merge-driver'
PLOTS = Path(__file__).resolve().parents[1] / 'experiments' / 'merge_driver' / 'plots.py'


def _plots():
    spec = importlib.util.spec_from_file_location('merge_driver_plots', PLOTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_figures_match_the_data():
    rendered = _plots().render_all(RESULTS / 'data')
    assert rendered, 'no figures rendered'
    for name, svg in rendered.items():
        committed = RESULTS / 'figures' / name
        assert committed.exists(), f'{name} is not committed; run experiments/merge_driver/plots.py'
        assert committed.read_text(encoding='utf-8') == svg, f'{name} is stale against the data'
