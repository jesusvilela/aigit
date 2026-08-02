import argparse
import json
from pathlib import Path

import pytest

from aigit.core import cmd_eval_lineage, cmd_validate_ruleset, evaluate_lineage_fixtures


FIXTURE = Path(__file__).parent / 'fixtures' / 'lineage_replay_v1.json'


def test_lineage_replay_fixture_meets_beta_core_thresholds() -> None:
    report = evaluate_lineage_fixtures(FIXTURE)

    assert report['case_count'] == 4
    assert report['metrics']['precision'] >= 0.95
    assert report['metrics']['recall'] >= 0.90
    assert all(not case['missing'] and not case['unexpected'] for case in report['cases'])


def test_cmd_eval_lineage_writes_deterministic_report(tmp_path: Path) -> None:
    output = tmp_path / 'lineage-report.json'
    args = argparse.Namespace(
        fixtures=str(FIXTURE), output=str(output), min_precision=0.95, min_recall=0.90
    )

    assert cmd_eval_lineage(args) == 0
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['metrics']['precision'] == 1.0
    assert report['metrics']['recall'] == 1.0


def test_cmd_eval_lineage_fails_closed_on_unmet_threshold(tmp_path: Path) -> None:
    output = tmp_path / 'lineage-report.json'
    args = argparse.Namespace(
        fixtures=str(FIXTURE), output=str(output), min_precision=1.01, min_recall=0.90
    )

    assert cmd_eval_lineage(args) == 1


def test_validate_ruleset_command_rejects_missing_ruleset(tmp_path: Path) -> None:
    args = argparse.Namespace(repo=str(tmp_path))
    assert cmd_validate_ruleset(args) == 1
    assert not (tmp_path / '.semantic').exists()


def test_lineage_replay_rejects_corpus_without_positive_edges(tmp_path: Path) -> None:
    fixture = tmp_path / 'negative-only.json'
    fixture.write_text(
        json.dumps(
            {
                'version': 1,
                'cases': [
                    {
                        'id': 'negative-only',
                        'base': [
                            {
                                'semantic_id': 'old',
                                'path': 'old.py',
                                'anchor': 'old',
                                'content': 'def old(): return 1',
                            }
                        ],
                        'head': [
                            {
                                'semantic_id': 'new',
                                'path': 'new.py',
                                'anchor': 'new',
                                'content': 'def new(value): return value * 2',
                            }
                        ],
                        'expected_lineage': [],
                    }
                ],
            }
        ),
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='at least one expected lineage edge'):
        evaluate_lineage_fixtures(fixture)
