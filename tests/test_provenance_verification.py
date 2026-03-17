import argparse
import json
from pathlib import Path

import pytest

from aigit import core


def test_verify_provenance_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    semantic_dir = tmp_path / '.semantic'
    semantic_dir.mkdir()
    prompt_hash = 'abc123def4567890feedfacecafebeef00000000000000000000000000000000'
    (semantic_dir / 'provenance.jsonl').write_text(
        json.dumps(
            {
                'commit': 'deadbeef',
                'agent': 'codex',
                'model': 'gpt-5.4',
                'prompt_hash': prompt_hash,
            }
        )
        + '\n',
        encoding='utf-8',
    )

    def fake_run_git(args: list[str], cwd: Path | None = None) -> str:
        assert cwd == tmp_path
        if args == ['rev-parse', 'HEAD']:
            return 'deadbeef'
        if args == ['show', '-s', '--format=%B', 'deadbeef']:
            return 'feat: example\n\nAI-Provenance: agent=codex;model=gpt-5.4;prompt-hash=abc123def4567890\n'
        raise AssertionError(f'unexpected git args: {args}')

    monkeypatch.setattr(core, '_run_git', fake_run_git)

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['commit'] == 'deadbeef'
    assert result['trailer']['agent'] == 'codex'
    assert result['trailer']['model'] == 'gpt-5.4'
    assert result['log_row']['prompt_hash'] == prompt_hash


def test_verify_provenance_rejects_missing_trailer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    semantic_dir = tmp_path / '.semantic'
    semantic_dir.mkdir()
    (semantic_dir / 'provenance.jsonl').write_text(json.dumps({'commit': 'deadbeef'}) + '\n', encoding='utf-8')

    def fake_run_git(args: list[str], cwd: Path | None = None) -> str:
        assert cwd == tmp_path
        if args == ['rev-parse', 'HEAD']:
            return 'deadbeef'
        if args == ['show', '-s', '--format=%B', 'deadbeef']:
            return 'feat: example\n'
        raise AssertionError(f'unexpected git args: {args}')

    monkeypatch.setattr(core, '_run_git', fake_run_git)

    with pytest.raises(ValueError, match='missing an AI-Provenance trailer'):
        core.verify_provenance(repo_root=tmp_path)


def test_verify_provenance_rejects_missing_log_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    semantic_dir = tmp_path / '.semantic'
    semantic_dir.mkdir()
    (semantic_dir / 'provenance.jsonl').write_text('', encoding='utf-8')

    def fake_run_git(args: list[str], cwd: Path | None = None) -> str:
        assert cwd == tmp_path
        if args == ['rev-parse', 'HEAD']:
            return 'deadbeef'
        if args == ['show', '-s', '--format=%B', 'deadbeef']:
            return 'feat: example\n\nAI-Provenance: agent=codex;model=gpt-5.4;prompt-hash=abc123def4567890\n'
        raise AssertionError(f'unexpected git args: {args}')

    monkeypatch.setattr(core, '_run_git', fake_run_git)

    with pytest.raises(ValueError, match='no provenance log row found'):
        core.verify_provenance(repo_root=tmp_path)


def test_cmd_verify_provenance_prints_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        core,
        'verify_provenance',
        lambda ref='HEAD', repo_root=Path('.'): {
            'commit': 'deadbeef',
            'trailer': {'agent': 'codex'},
            'log_row': {'commit': 'deadbeef'},
            'provenance_path': '.semantic/provenance.jsonl',
        },
    )

    result = core.cmd_verify_provenance(argparse.Namespace(ref='HEAD'))

    assert result == 0
    assert json.loads(capsys.readouterr().out)['commit'] == 'deadbeef'