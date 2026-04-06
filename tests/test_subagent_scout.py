import json
from pathlib import Path

from aigit import core


def test_scout_repo_summarizes_workspace(tmp_path: Path) -> None:
    (tmp_path / 'aigit').mkdir()
    (tmp_path / 'aigit' / 'core.py').write_text('print("ok")\n', encoding='utf-8')
    (tmp_path / 'README.md').write_text('# Demo\n', encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_demo.py').write_text('def test_demo():\n    assert True\n', encoding='utf-8')

    summary = core.scout_repo(tmp_path)

    assert summary.file_count == 3
    assert summary.python_file_count == 2
    assert summary.markdown_file_count == 1
    assert summary.test_file_count == 1
    assert summary.recommended_tool == 'devx-quickcheck'
    assert 'aigit improve --repo .' in summary.recommended_interfaces
    assert summary.largest_files


def test_cmd_subagent_scout_writes_report_and_bootstraps_tool(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / '__init__.py').write_text('__all__ = []\n', encoding='utf-8')

    args = type(
        'Args',
        (),
        {
            'repo': '.',
            'output': '.aigit/runtime/subagent_scout_report.md',
            'json_output': '.aigit/runtime/subagent_scout_report.json',
            'bootstrap_tool': True,
            'force': False,
        },
    )()

    result = core.cmd_subagent_scout(args)

    assert result == 0
    report = Path('.aigit/runtime/subagent_scout_report.md')
    assert report.exists()
    report_text = report.read_text(encoding='utf-8')
    assert '# Subagent Scout Report' in report_text
    assert 'recommended_tool' in report_text
    assert 'AIGit Developer Interfaces' in report_text

    json_report = Path('.aigit/runtime/subagent_scout_report.json')
    assert json_report.exists()
    payload = json.loads(json_report.read_text(encoding='utf-8'))
    assert payload['recommended_tool'] == 'repo-health-baseline'
    assert 'recommended_interfaces' in payload

    tool_script = Path('scripts/devx_quickcheck.sh')
    assert tool_script.exists()
    script_text = tool_script.read_text(encoding='utf-8')
    assert 'AIGIT_BIN="aigit"' in script_text
    assert '${AIGIT_BIN} improve --repo .' in script_text
