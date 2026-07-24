import argparse
import json
from pathlib import Path

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


def test_validate_ruleset_command_accepts_default_ruleset(tmp_path: Path) -> None:
    args = argparse.Namespace(repo=str(tmp_path))
    assert cmd_validate_ruleset(args) == 0
