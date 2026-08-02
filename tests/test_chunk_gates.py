"""Tests for `chunk --strict` (unparseable) and `chunk --check` (stale) gates."""
import argparse

from aigit import core


def _chunk(tmp_path, strict=False, check=False):
    return core.cmd_chunk(argparse.Namespace(repo=str(tmp_path), strict=strict, check=check))


def test_strict_fails_on_unparseable_python(tmp_path):
    (tmp_path / 'ok.py').write_text('def ok():\n    return 1\n', encoding='utf-8')
    (tmp_path / 'bad.py').write_text('def broken(:\n    return 1\n', encoding='utf-8')
    # non-strict tolerates it (warns), strict fails
    assert _chunk(tmp_path, strict=False) == 0
    assert _chunk(tmp_path, strict=True) == 1


def test_strict_passes_on_clean_repo(tmp_path):
    (tmp_path / 'ok.py').write_text('def ok():\n    return 1\n', encoding='utf-8')
    assert _chunk(tmp_path, strict=True) == 0


def test_check_detects_stale_after_edit(tmp_path):
    src = tmp_path / 'm.py'
    src.write_text('def a():\n    return 1\n', encoding='utf-8')
    assert _chunk(tmp_path) == 0           # write artifacts
    assert _chunk(tmp_path, check=True) == 0  # fresh
    src.write_text('def a():\n    return 1\n\n\ndef b():\n    return 2\n', encoding='utf-8')
    assert _chunk(tmp_path, check=True) == 1  # stale: forgot to re-chunk
    assert _chunk(tmp_path) == 0              # re-chunk
    assert _chunk(tmp_path, check=True) == 0  # fresh again


def test_chunk_preflight_rejects_invalid_ruleset(tmp_path, capsys):
    core.ensure_semantic_scaffold(tmp_path)
    (tmp_path / '.semantic/ruleset.yaml').write_text(
        'version: 99\nparsers:\n  default: file\n',
        encoding='utf-8',
    )

    assert _chunk(tmp_path) == 1
    assert 'ruleset preflight failed' in capsys.readouterr().err


def test_chunk_preflight_rejects_incompatible_semantic_schema(tmp_path, capsys):
    core.ensure_semantic_scaffold(tmp_path)
    (tmp_path / '.semantic/schema_version').write_text('2\n', encoding='utf-8')

    assert _chunk(tmp_path) == 1
    assert 'unsupported semantic schema version' in capsys.readouterr().err
