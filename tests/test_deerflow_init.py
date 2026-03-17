from pathlib import Path

from aigit import core


def test_bootstrap_deerflow_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(core, 'DEERFLOW_ENV_FILE', Path('.deerflow/.env.example'))
    monkeypatch.setattr(core, 'DEERFLOW_CONFIG_FILE', Path('.deerflow/config.yaml'))
    monkeypatch.setattr(core, 'DEERFLOW_LAUNCH_SCRIPT', Path('scripts/run_deerflow.sh'))

    core.bootstrap_deerflow_files()

    assert Path('.deerflow/.env.example').exists()
    assert Path('.deerflow/config.yaml').exists()
    assert Path('scripts/run_deerflow.sh').exists()
    assert 'subagent_enabled: true' in Path('.deerflow/config.yaml').read_text(encoding='utf-8')
