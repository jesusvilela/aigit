from pathlib import Path

import pytest

from aigit.core import ensure_semantic_scaffold, validate_ruleset_file


def test_validate_ruleset_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    ensure_semantic_scaffold()
    parsed = validate_ruleset_file()
    assert parsed['version'] == '1'
    assert parsed['parsers']['default'] == 'file'


def test_validate_ruleset_rejects_unknown_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    ensure_semantic_scaffold()
    ruleset = Path('.semantic/ruleset.yaml')
    ruleset.write_text(
        'version: 1\nparsers:\n  .py: python-ast\n  .md: markdown-headings\n  default: made-up-parser\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='unsupported parser backend'):
        validate_ruleset_file()
