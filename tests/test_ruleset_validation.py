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


@pytest.mark.parametrize(
    ('old', 'new', 'message'),
    [
        ('version: 1', 'version: 2', 'unsupported ruleset version'),
        (
            '  strategy: path+anchor+type',
            '  strategy: random',
            'unsupported identity strategy',
        ),
        ('  line_endings: lf', '  line_endings: native', 'unsupported line-ending policy'),
    ],
)
def test_validate_ruleset_rejects_unsupported_semantics(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    ensure_semantic_scaffold(tmp_path)
    ruleset = tmp_path / '.semantic/ruleset.yaml'
    ruleset.write_text(
        ruleset.read_text(encoding='utf-8').replace(old, new),
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match=message):
        validate_ruleset_file(tmp_path)


def test_validate_ruleset_rejects_duplicate_keys(tmp_path: Path) -> None:
    ensure_semantic_scaffold(tmp_path)
    ruleset = tmp_path / '.semantic/ruleset.yaml'
    ruleset.write_text(
        ruleset.read_text(encoding='utf-8') + 'version: 1\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='duplicate ruleset key'):
        validate_ruleset_file(tmp_path)
