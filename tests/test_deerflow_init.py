import os
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from aigit import core


def test_bootstrap_deerflow_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(core, 'DEERFLOW_ENV_FILE', Path('.deerflow/.env.example'))
    monkeypatch.setattr(core, 'DEERFLOW_CONFIG_FILE', Path('.deerflow/config.yaml'))
    monkeypatch.setattr(core, 'DEERFLOW_AGENTS_DIR', Path('.deerflow/agents'))
    monkeypatch.setattr(core, 'DEERFLOW_USER_PROFILE_FILE', Path('.deerflow/USER.md'))
    monkeypatch.setattr(core, 'DEERFLOW_LAUNCH_SCRIPT', Path('scripts/run_deerflow.sh'))
    monkeypatch.setattr(core, 'DEERFLOW_EPIC_LAUNCH_SCRIPT', Path('scripts/run_deerflow_epics.sh'))
    monkeypatch.setattr(core, 'DEERFLOW_RECOVERY_SCRIPT', Path('scripts/recover_deerflow.sh'))

    core.bootstrap_deerflow_files()

    assert Path('.deerflow/.env.example').exists()
    assert Path('.deerflow/config.yaml').exists()
    assert Path('.deerflow/USER.md').exists()
    assert Path('.deerflow/agents/aigit-orchestrator/config.yaml').exists()
    assert Path('.deerflow/agents/aigit-semantic-maintainer/SOUL.md').exists()
    assert Path('scripts/run_deerflow.sh').exists()
    assert Path('scripts/run_deerflow_epics.sh').exists()
    assert Path('scripts/recover_deerflow.sh').exists()
    config_text = Path('.deerflow/config.yaml').read_text(encoding='utf-8')
    env_text = Path('.deerflow/.env.example').read_text(encoding='utf-8')
    assert 'subagent_enabled: true' in config_text
    assert 'workspace_repo_subdir: repo' in config_text
    assert 'assistant_id: aigit-orchestrator' in config_text
    assert 'name: claude-sonnet-4' in config_text
    assert 'name: deepseek-v3.2' in config_text
    assert 'path: ' in config_text
    assert f'host_path: "{tmp_path.as_posix()}"' in config_text
    assert f'container_path: "{tmp_path.as_posix()}"' in config_text
    assert 'use: deerflow.sandbox.tools:bash_tool' in config_text
    assert 'use: deerflow.sandbox.tools:read_file_tool' in config_text
    assert 'ANTHROPIC_API_KEY=' in env_text
    assert 'GOOGLE_API_KEY=' in env_text
    assert 'DEEPSEEK_API_KEY=' in env_text
    launch_text = Path('scripts/run_deerflow_epics.sh').read_text(encoding='utf-8')
    assert 'DEER_FLOW_ROOT' in Path('scripts/run_deerflow.sh').read_text(encoding='utf-8')
    assert 'LOCAL_AGENTS_DIR' in Path('scripts/run_deerflow.sh').read_text(encoding='utf-8')
    assert f'Live development directory mount: {tmp_path.as_posix()}' in launch_text
    assert f'Prefer DeerFlow work in: {tmp_path.as_posix()}' in launch_text
    assert 'docker restart deer-flow-nginx' in Path('scripts/recover_deerflow.sh').read_text(encoding='utf-8')


def test_build_epic_objective_bundle(tmp_path: Path) -> None:
    epics_dir = tmp_path / 'docs' / 'epics'
    epics_dir.mkdir(parents=True)
    (epics_dir / 'EPIC-01-test.md').write_text(
        '# EPIC-01: Example\n\n'
        '## Goal\n'
        'Ship the example objective.\n\n'
        '## Deliverables\n'
        '- First outcome\n'
        '- Second outcome\n\n'
        '## Acceptance\n'
        '- The example works.\n',
        encoding='utf-8',
    )
    (epics_dir / 'EPIC-02-next.md').write_text(
        '# EPIC-02: Next\n\n'
        '## Goal\n'
        'Ship the next objective.\n\n'
        '## Deliverables\n'
        '- Another outcome\n\n'
        '## Acceptance\n'
        'The next example works.\n',
        encoding='utf-8',
    )

    output_dir = tmp_path / '.deerflow' / 'objectives'
    queue_file = tmp_path / '.deerflow' / 'epic_queue.json'

    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        written = core.build_epic_objective_bundle(epics_dir, output_dir, queue_file)
    finally:
        os.chdir(cwd)

    assert output_dir.joinpath('EPIC-01.md').exists()
    assert output_dir.joinpath('EPIC-02.md').exists()
    assert output_dir.joinpath('ALL_EPICS.md').exists()
    assert queue_file.exists()
    assert any(path.name == 'ALL_EPICS.md' for path in written)
    objective_text = output_dir.joinpath('EPIC-01.md').read_text(encoding='utf-8')
    assert 'Execution Guardrails' in objective_text
    assert f'Prefer the live development directory `{tmp_path.as_posix()}`' in objective_text
    assert '## Acceptance\n- The example works.\n' in objective_text
    assert '- -' not in output_dir.joinpath('ALL_EPICS.md').read_text(encoding='utf-8')


def test_sync_deerflow_harness_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(core, 'DEERFLOW_CONFIG_FILE', Path('.deerflow/config.yaml'))
    monkeypatch.setattr(core, 'DEERFLOW_RUNTIME_ENV_FILE', Path('.deerflow/.env'))
    monkeypatch.setattr(core, 'DEERFLOW_AGENTS_DIR', Path('.deerflow/agents'))
    monkeypatch.setattr(core, 'DEERFLOW_USER_PROFILE_FILE', Path('.deerflow/USER.md'))
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_DIR', Path('.deerflow/vendor/deer-flow'))
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_CONFIG_FILE', Path('.deerflow/vendor/deer-flow/config.yaml'))
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_ENV_FILE', Path('.deerflow/vendor/deer-flow/.env'))
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_RUNTIME_DIR', Path('.deerflow/vendor/deer-flow/backend/.deer-flow'))
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_AGENTS_DIR', Path('.deerflow/vendor/deer-flow/backend/.deer-flow/agents'))
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_USER_PROFILE_FILE', Path('.deerflow/vendor/deer-flow/backend/.deer-flow/USER.md'))

    Path('.deerflow').mkdir()
    Path('.deerflow/vendor/deer-flow/backend/.deer-flow').mkdir(parents=True)
    Path('.deerflow/config.yaml').write_text('models:\n  - name: test\n', encoding='utf-8')
    Path('.deerflow/.env').write_text('OPENAI_API_KEY=test\n', encoding='utf-8')
    Path('.deerflow/USER.md').write_text('# operator\n', encoding='utf-8')
    Path('.deerflow/agents/aigit-orchestrator').mkdir(parents=True)
    Path('.deerflow/agents/aigit-orchestrator/config.yaml').write_text('name: aigit-orchestrator\n', encoding='utf-8')
    Path('.deerflow/agents/aigit-orchestrator/SOUL.md').write_text('ship it\n', encoding='utf-8')

    synced = core.sync_deerflow_harness_files()

    assert Path('.deerflow/vendor/deer-flow/config.yaml').read_text(encoding='utf-8') == 'models:\n  - name: test\n'
    assert Path('.deerflow/vendor/deer-flow/.env').read_text(encoding='utf-8') == 'OPENAI_API_KEY=test\n'
    assert Path('.deerflow/vendor/deer-flow/backend/.deer-flow/USER.md').read_text(encoding='utf-8') == '# operator\n'
    assert Path('.deerflow/vendor/deer-flow/backend/.deer-flow/agents/aigit-orchestrator/config.yaml').read_text(encoding='utf-8') == 'name: aigit-orchestrator\n'
    assert Path('.deerflow/vendor/deer-flow/backend/.deer-flow/agents/aigit-orchestrator/SOUL.md').read_text(encoding='utf-8') == 'ship it\n'
    assert Path('.deerflow/vendor/deer-flow/config.yaml') in synced
    assert Path('.deerflow/vendor/deer-flow/.env') in synced
    assert Path('.deerflow/vendor/deer-flow/backend/.deer-flow/USER.md') in synced


def test_deerflow_repo_import_and_export_round_trip(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / 'repo'
    vendor_dir = tmp_path / '.deerflow' / 'vendor' / 'deer-flow'
    vendor_dir.mkdir(parents=True)
    repo_root.mkdir()

    (repo_root / 'README.md').write_text('hello\n', encoding='utf-8')
    (repo_root / 'pkg').mkdir()
    (repo_root / 'pkg' / '__init__.py').write_text('__all__ = []\n', encoding='utf-8')
    (repo_root / '.git').mkdir()
    (repo_root / '.git' / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    (repo_root / '.semantic').mkdir()
    (repo_root / '.semantic' / 'manifest.jsonl').write_text('{}\n', encoding='utf-8')
    (repo_root / '.deerflow').mkdir()
    (repo_root / '.deerflow' / 'config.yaml').write_text('models: []\n', encoding='utf-8')
    (repo_root / '.deerflow' / '.env').write_text('OPENAI_API_KEY=secret\n', encoding='utf-8')
    (repo_root / '.deerflow' / 'vendor').mkdir()
    (repo_root / '.deerflow' / 'vendor' / 'ignored.txt').write_text('skip me\n', encoding='utf-8')

    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_DIR', vendor_dir)

    imported = core.import_repo_to_deerflow_thread('thread_123', repo_root)
    workspace_repo = core.deerflow_repo_workspace_dir('thread_123')

    assert imported.sandbox_workspace == '/mnt/user-data/workspace/repo'
    assert workspace_repo.joinpath('README.md').read_text(encoding='utf-8') == 'hello\n'
    assert workspace_repo.joinpath('.git', 'HEAD').read_text(encoding='utf-8') == 'ref: refs/heads/main\n'
    assert not workspace_repo.joinpath('.deerflow', '.env').exists()
    assert not workspace_repo.joinpath('.deerflow', 'vendor').exists()
    assert imported.metadata_file == core.deerflow_sync_metadata_file('thread_123')

    workspace_repo.joinpath('README.md').write_text('updated\n', encoding='utf-8')
    workspace_repo.joinpath('new_file.txt').write_text('sandbox change\n', encoding='utf-8')
    workspace_repo.joinpath('.git', 'HEAD').write_text('sandbox metadata\n', encoding='utf-8')

    exported = core.export_repo_from_deerflow_thread('thread_123', repo_root)

    assert exported.files_copied >= 2
    assert repo_root.joinpath('README.md').read_text(encoding='utf-8') == 'updated\n'
    assert repo_root.joinpath('new_file.txt').read_text(encoding='utf-8') == 'sandbox change\n'
    assert repo_root.joinpath('.git', 'HEAD').read_text(encoding='utf-8') == 'ref: refs/heads/main\n'


def test_deerflow_thread_path_validation() -> None:
    with pytest.raises(ValueError):
        core.deerflow_thread_workspace_dir('../bad-thread')

    with pytest.raises(ValueError):
        core.deerflow_repo_workspace_dir('ok-thread', '../repo')


def test_init_deerflow_skips_pull_when_vendor_is_dirty(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    vendor_dir = Path('.deerflow/vendor/deer-flow')
    vendor_dir.mkdir(parents=True)

    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_DIR', vendor_dir)
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_CONFIG_FILE', vendor_dir / 'config.yaml')
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_ENV_FILE', vendor_dir / '.env')

    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> CompletedProcess[str]:
        calls.append(args)
        if args == ['git', '-C', str(vendor_dir), 'status', '--porcelain']:
            return CompletedProcess(args, 0, stdout=' M backend/packages/harness/deerflow/sandbox/tools.py\n', stderr='')
        if args == ['git', '-C', str(vendor_dir), 'pull', '--ff-only']:
            raise AssertionError('pull should not run when the vendor checkout is dirty')
        if args == ['make', 'config']:
            return CompletedProcess(args, 0, stdout='', stderr='')
        return CompletedProcess(args, 0, stdout='', stderr='')

    monkeypatch.setattr(core.subprocess, 'run', fake_run)
    monkeypatch.setattr(core, 'sync_deerflow_harness_files', lambda: [])

    result = core.cmd_init_deerflow(type('Args', (), {'repo': 'https://example.invalid/deer-flow.git', 'skip_clone': False})())

    output = capsys.readouterr().out
    assert result == 0
    assert 'skipping upstream pull' in output
    assert ['git', '-C', str(vendor_dir), 'status', '--porcelain'] in calls


def test_cmd_up_recovers_deerflow_and_starts_local_services(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(core, 'DEERFLOW_VENDOR_DIR', Path('.deerflow/vendor/deer-flow'))
    monkeypatch.setattr(core, 'DEERFLOW_RECOVERY_SCRIPT', Path('scripts/recover_deerflow.sh'))

    Path('.deerflow/vendor/deer-flow').mkdir(parents=True)
    Path('scripts').mkdir()
    Path('scripts/recover_deerflow.sh').write_text('#!/usr/bin/env bash\n', encoding='utf-8')

    bootstrap_calls: list[str] = []
    monkeypatch.setattr(core, 'bootstrap_deerflow_files', lambda: bootstrap_calls.append('bootstrapped'))
    monkeypatch.setattr(core, 'ensure_deerflow_runtime_env', lambda: True)
    monkeypatch.setattr(core, 'sync_deerflow_harness_files', lambda: [Path('.deerflow/vendor/deer-flow/config.yaml')])
    monkeypatch.setattr(core, 'missing_deerflow_env_keys', lambda required=('OPENAI_API_KEY',): ['OPENAI_API_KEY'])

    run_calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> CompletedProcess[str]:
        run_calls.append(args)
        return CompletedProcess(args, 0, stdout='', stderr='')

    monkeypatch.setattr(core.subprocess, 'run', fake_run)

    service_requests: list[tuple[str, str, list[str], float]] = []

    def fake_ensure_background_service(
        service_name: str,
        repo_root: Path,
        health_url: str,
        cli_args: list[str],
        startup_timeout: float,
    ) -> tuple[bool, str]:
        service_requests.append((service_name, health_url, cli_args, startup_timeout))
        return True, f'{service_name} ok'

    monkeypatch.setattr(core, '_ensure_background_service', fake_ensure_background_service)

    args = SimpleNamespace(
        deerflow_repo='https://example.invalid/deer-flow.git',
        bootstrap_deerflow=False,
        skip_clone=False,
        skip_serve_api=False,
        skip_admin_ui=False,
        api_host='127.0.0.1',
        api_port=8765,
        admin_host='127.0.0.1',
        admin_port=7860,
    )

    result = core.cmd_up(args)

    output = capsys.readouterr().out
    assert result == 0
    assert bootstrap_calls == ['bootstrapped']
    assert run_calls == [[str(Path('scripts/recover_deerflow.sh').resolve())]]
    assert service_requests == [
        ('serve-api', 'http://127.0.0.1:8765/healthz', ['serve-api', '--host', '127.0.0.1', '--port', '8765'], 10),
        ('admin-ui', f'http://127.0.0.1:7860', ['admin-ui', '--repo', str(tmp_path), '--host', '127.0.0.1', '--port', '7860'], 30),
    ]
    assert 'warning: missing DeerFlow env keys: OPENAI_API_KEY' in output
    assert 'AIGit stack is up:' in output
