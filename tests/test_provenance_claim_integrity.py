"""Claim integrity regressions, including compatibility with legacy HMACs.

The trailer must identify one complete claim: matching agent/model, a 16--64
hex prompt prefix, and exactly one matching full (64-hex) prompt hash. Select
among matching rows before preferring a valid signature. Reject ambiguous
trailers, unreadable log records, and writer identities containing delimiters.
All Git operations are mocked; JSONL fixtures live only under tmp_path.
"""

import argparse
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from aigit import core

COMMIT = 'd' * 40
KEY = 'public-regression-fixture-key'
PROMPT = 'provenance claim integrity regression'
PROMPT_HASH = hashlib.sha256(PROMPT.encode('utf-8')).hexdigest()
PREFIX = PROMPT_HASH[:16]


def _signed_row(**overrides: str) -> dict[str, str]:
    row = {
        'commit': COMMIT,
        'agent': 'codex',
        'model': 'gpt-5.4',
        'prompt_hash': PROMPT_HASH,
    }
    row.update(overrides)
    # Keep the existing wire encoding as an oracle: no signature migration.
    payload = '\n'.join(row[field] for field in ('commit', 'agent', 'model', 'prompt_hash'))
    row['signature'] = hmac.new(KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return row


def _trailer(agent: str = 'codex', model: str = 'gpt-5.4', prompt_hash: str = PREFIX) -> str:
    return f'AI-Provenance: agent={agent};model={model};prompt-hash={prompt_hash}'


def _install_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, str]],
    *,
    trailer: str | None = None,
    message: str | None = None,
    raw_log: str | None = None,
) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('AIGIT_PROVENANCE_KEY', KEY)
    if message is None:
        message = f'feat: fixture\n\n{_trailer() if trailer is None else trailer}\n'

    def fake_git(args: list[str], cwd: Path | None = None) -> str:
        assert cwd is None or cwd == tmp_path
        if args == ['rev-parse', 'HEAD']:
            return COMMIT
        if args == ['show', '-s', '--format=%B', COMMIT]:
            return message
        raise AssertionError(f'unexpected Git command: {args}')

    monkeypatch.setattr(core, '_run_git', fake_git)
    path = tmp_path / '.semantic' / 'provenance.jsonl'
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        raw_log if raw_log is not None else ''.join(json.dumps(row) + '\n' for row in rows),
        encoding='utf-8',
    )
    return path


@pytest.mark.parametrize('length', [16, 32, 64])
@pytest.mark.parametrize('uppercase', [False, True], ids=['lowercase', 'uppercase'])
def test_valid_hex_prompt_prefix_preserves_signed_claim(tmp_path, monkeypatch, length, uppercase):
    prefix = PROMPT_HASH[:length]
    _install_claim(
        tmp_path, monkeypatch, [_signed_row()],
        trailer=_trailer(prompt_hash=prefix.upper() if uppercase else prefix),
    )

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['signed'] is True
    assert result['log_row'] == _signed_row()


def test_uppercase_row_hash_keeps_its_original_legacy_signature(tmp_path, monkeypatch):
    row = _signed_row(prompt_hash=PROMPT_HASH.upper())
    _install_claim(tmp_path, monkeypatch, [row])

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['signed'] is True
    assert result['log_row'] == row


def test_cmd_commit_emits_a_verifiable_16_hex_prefix(tmp_path, monkeypatch):
    calls = []

    def fake_commit(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(core.subprocess, 'run', fake_commit)
    args = argparse.Namespace(message='feat: fixture', agent='codex', model='gpt-5.4', prompt=PROMPT)
    assert core.cmd_commit(args) == 0
    assert calls == [(['git', 'commit', '-m', f'feat: fixture\n\n{_trailer()}\n'], {'check': True})]
    _install_claim(tmp_path, monkeypatch, [_signed_row()], message=calls[0][0][3])

    assert core.verify_provenance(repo_root=tmp_path)['signed'] is True


def test_matching_unsigned_claim_remains_valid_without_a_key(tmp_path, monkeypatch):
    row = _signed_row()
    row.pop('signature')
    _install_claim(tmp_path, monkeypatch, [row])
    monkeypatch.delenv('AIGIT_PROVENANCE_KEY')

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['signed'] is False
    assert result['log_row'] == row


def test_record_provenance_preserves_legacy_hmac_encoding(tmp_path, monkeypatch):
    path = _install_claim(tmp_path, monkeypatch, [])
    args = argparse.Namespace(agent='codex', model='gpt-5.4', prompt=PROMPT)

    assert core.cmd_record_provenance(args) == 0

    row = json.loads(path.read_text(encoding='utf-8'))
    assert {field: row[field] for field in _signed_row()} == _signed_row()
    assert core.verify_provenance(repo_root=tmp_path)['signed'] is True


@pytest.mark.parametrize('field', ['agent', 'model'])
def test_signed_log_does_not_authenticate_a_contradictory_trailer(tmp_path, monkeypatch, field):
    _install_claim(tmp_path, monkeypatch, [_signed_row()], trailer=_trailer(**{field: 'someone-else'}))

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize('field', ['agent', 'model', 'prompt-hash'])
def test_trailer_requires_every_claim_field(tmp_path, monkeypatch, field):
    parts = _trailer().removeprefix('AI-Provenance: ').split(';')
    trailer = 'AI-Provenance: ' + ';'.join(part for part in parts if not part.startswith(f'{field}='))
    _install_claim(tmp_path, monkeypatch, [_signed_row()], trailer=trailer)

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize(
    'prefix', ['', PREFIX[:1], PREFIX[:15], PROMPT_HASH + '0', PREFIX[:-1] + 'g'],
    ids=['empty', 'one-hex', 'fifteen-hex', 'sixty-five-hex', 'non-hex'],
)
def test_trailer_rejects_missing_strength_or_invalid_hash_syntax(tmp_path, monkeypatch, prefix):
    _install_claim(tmp_path, monkeypatch, [_signed_row()], trailer=_trailer(prompt_hash=prefix))

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize(
    'invalid_hash',
    [None, '', PROMPT_HASH[:61], PROMPT_HASH[:63], PROMPT_HASH + '0', PREFIX + 'g' * 48],
    ids=['missing', 'empty', 'sixty-one-hex', 'sixty-three-hex', 'sixty-five-hex', 'non-hex'],
)
def test_log_requires_a_complete_64_hex_prompt_hash(tmp_path, monkeypatch, invalid_hash):
    row = _signed_row()
    if invalid_hash is None:
        row.pop('prompt_hash')
    else:
        row['prompt_hash'] = invalid_hash
    # No signature/key requirement: even plain verification must reject this.
    row.pop('signature')
    _install_claim(tmp_path, monkeypatch, [row])
    monkeypatch.delenv('AIGIT_PROVENANCE_KEY')

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize('field', ['agent', 'model', 'prompt-hash'])
@pytest.mark.parametrize('same_value', [False, True], ids=['contradictory', 'identical'])
def test_duplicate_trailer_fields_are_ambiguous(tmp_path, monkeypatch, field, same_value):
    values = {'agent': 'codex', 'model': 'gpt-5.4', 'prompt-hash': PREFIX}
    first = values[field] if same_value else 'contradictory'
    # Last-wins parsing must not erase the first occurrence.
    trailer = _trailer().replace('AI-Provenance: ', f'AI-Provenance: {field}={first};', 1)
    _install_claim(tmp_path, monkeypatch, [_signed_row()], trailer=trailer)

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize('order', ['contradictory-first', 'contradictory-last', 'identical'])
def test_multiple_provenance_trailer_lines_are_ambiguous(tmp_path, monkeypatch, order):
    valid, contradictory = _trailer(), _trailer(agent='someone-else')
    lines = {
        'contradictory-first': [contradictory, valid],
        'contradictory-last': [valid, contradictory],
        'identical': [valid, valid],
    }[order]
    _install_claim(tmp_path, monkeypatch, [_signed_row()], trailer='\n'.join(lines))

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize('field', ['agent', 'model', 'prompt_hash'])
def test_later_contradictory_row_cannot_mask_matching_signed_claim(tmp_path, monkeypatch, field):
    valid = _signed_row()
    replacement = '0' * 64 if field == 'prompt_hash' else 'someone-else'
    later = _signed_row(**{field: replacement})
    _install_claim(tmp_path, monkeypatch, [valid, later])

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['log_row'] == valid
    assert result['signed'] is True


@pytest.mark.parametrize('later_signature', [None, '0' * 64], ids=['unsigned', 'invalid-signature'])
def test_later_matching_row_cannot_mask_valid_signature(tmp_path, monkeypatch, later_signature):
    valid = _signed_row()
    later = dict(valid)
    if later_signature is None:
        later.pop('signature')
    else:
        later['signature'] = later_signature
    _install_claim(tmp_path, monkeypatch, [valid, later])

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['log_row'] == valid
    assert result['signed'] is True
    assert core.cmd_verify_provenance(argparse.Namespace(ref='HEAD', require_signature=True)) == 0


@pytest.mark.parametrize('reverse', [False, True], ids=['original-order', 'reversed-order'])
def test_distinct_full_hashes_matching_one_prefix_are_ambiguous(tmp_path, monkeypatch, reverse):
    other_hash = PREFIX + ('0' if PROMPT_HASH[16] != '0' else '1') + PROMPT_HASH[17:]
    rows = [_signed_row(), _signed_row(prompt_hash=other_hash)]
    _install_claim(tmp_path, monkeypatch, rows[::-1] if reverse else rows)

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


@pytest.mark.parametrize('uppercase', [False, True], ids=['identical-record', 'case-variant-hash'])
def test_repeated_same_full_hash_is_not_a_prefix_ambiguity(tmp_path, monkeypatch, uppercase):
    repeated = _signed_row(prompt_hash=PROMPT_HASH.upper()) if uppercase else _signed_row()
    _install_claim(tmp_path, monkeypatch, [_signed_row(), repeated])

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['signed'] is True
    assert result['log_row']['prompt_hash'].lower() == PROMPT_HASH


def test_contradictory_identity_is_filtered_before_hash_disambiguation(tmp_path, monkeypatch):
    valid = _signed_row()
    other_hash = PREFIX + ('0' if PROMPT_HASH[16] != '0' else '1') + PROMPT_HASH[17:]
    contradictory = _signed_row(agent='someone-else', prompt_hash=other_hash)
    _install_claim(tmp_path, monkeypatch, [valid, contradictory])

    result = core.verify_provenance(repo_root=tmp_path)

    assert result['log_row'] == valid
    assert result['signed'] is True


@pytest.mark.parametrize(
    'bad_line,append',
    [('{"commit":', False), ('{"commit":', True), ('not-json', True), ('[]', False), ('null', True)],
    ids=['truncated-before', 'truncated-after', 'malformed-after', 'array-before', 'null-after'],
)
def test_verifier_rejects_bad_jsonl_even_alongside_a_valid_signed_row(tmp_path, monkeypatch, bad_line, append):
    valid = json.dumps(_signed_row()) + '\n'
    # An unterminated final record must not be silently ignored.
    raw_log = valid + bad_line if append else bad_line + '\n' + valid
    _install_claim(tmp_path, monkeypatch, [], raw_log=raw_log)

    with pytest.raises(ValueError):
        core.verify_provenance(repo_root=tmp_path)


def test_complete_jsonl_record_does_not_require_a_final_newline(tmp_path, monkeypatch):
    _install_claim(tmp_path, monkeypatch, [], raw_log=json.dumps(_signed_row()))

    assert core.verify_provenance(repo_root=tmp_path)['signed'] is True


@pytest.mark.parametrize('writer_name', ['cmd_record_provenance', 'cmd_commit'])
@pytest.mark.parametrize('field', ['agent', 'model'])
@pytest.mark.parametrize(
    'value', ['', ' ', ' leading', 'trailing ', 'split\nclaim', 'split\rclaim', 'split;model=forged'],
    ids=['empty', 'whitespace-only', 'leading-space', 'trailing-space', 'newline', 'carriage-return', 'semicolon'],
)
def test_writers_reject_ambiguous_identities_before_side_effects(tmp_path, monkeypatch, writer_name, field, value):
    path = _install_claim(tmp_path, monkeypatch, [_signed_row()])
    original_log = path.read_text(encoding='utf-8')
    commit_calls = []
    monkeypatch.setattr(core.subprocess, 'run', lambda *args, **kwargs: commit_calls.append((args, kwargs)))
    args = argparse.Namespace(message='feat: fixture', agent='codex', model='gpt-5.4', prompt=PROMPT)
    setattr(args, field, value)

    with pytest.raises(ValueError):
        getattr(core, writer_name)(args)

    assert commit_calls == []
    assert path.read_text(encoding='utf-8') == original_log
