"""Tests for HMAC-signed provenance and --require-signature."""
import argparse
import json
from pathlib import Path

import pytest

from aigit import core

COMMIT = 'deadbeef'
PROMPT_HASH = 'abc123def4567890feedfacecafebeef00000000000000000000000000000000'


def _fake_git(trailer='AI-Provenance: agent=codex;model=gpt-5.4;prompt-hash=abc123def4567890'):
    def _run(args, cwd=None):
        if args == ['rev-parse', 'HEAD']:
            return COMMIT
        if args == ['show', '-s', '--format=%B', COMMIT]:
            return f'feat: x\n\n{trailer}\n'
        raise AssertionError(args)
    return _run


def _write_row(tmp_path, **overrides):
    row = {'commit': COMMIT, 'agent': 'codex', 'model': 'gpt-5.4', 'prompt_hash': PROMPT_HASH}
    row.update(overrides)
    sem = tmp_path / '.semantic'
    sem.mkdir(exist_ok=True)
    (sem / 'provenance.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')


def test_signature_is_deterministic_and_key_bound():
    a = core._provenance_signature('secret', COMMIT, 'codex', 'gpt-5.4', PROMPT_HASH)
    assert a == core._provenance_signature('secret', COMMIT, 'codex', 'gpt-5.4', PROMPT_HASH)
    assert a != core._provenance_signature('other-key', COMMIT, 'codex', 'gpt-5.4', PROMPT_HASH)
    assert a != core._provenance_signature('secret', COMMIT, 'attacker', 'gpt-5.4', PROMPT_HASH)


def test_valid_signature_verifies_as_signed(tmp_path, monkeypatch):
    monkeypatch.setenv('AIGIT_PROVENANCE_KEY', 'secret')
    sig = core._provenance_signature('secret', COMMIT, 'codex', 'gpt-5.4', PROMPT_HASH)
    _write_row(tmp_path, signature=sig)
    monkeypatch.setattr(core, '_run_git', _fake_git())
    result = core.verify_provenance(repo_root=tmp_path)
    assert result['signed'] is True


def test_tampered_row_fails_signature(tmp_path, monkeypatch):
    monkeypatch.setenv('AIGIT_PROVENANCE_KEY', 'secret')
    sig = core._provenance_signature('secret', COMMIT, 'codex', 'gpt-5.4', PROMPT_HASH)
    # signature was made for agent=codex but the row now claims a different agent
    _write_row(tmp_path, agent='security-team', signature=sig,
               # trailer must still match the (forged) row's prompt hash to reach the sig check
               )
    monkeypatch.setattr(core, '_run_git', _fake_git('AI-Provenance: agent=security-team;model=gpt-5.4;prompt-hash=abc123def4567890'))
    result = core.verify_provenance(repo_root=tmp_path)
    assert result['signed'] is False


def test_require_signature_rejects_unsigned_forgery(tmp_path, monkeypatch, capsys):
    # Reproduces C4: a hand-written plaintext row (no signature) must be rejected.
    monkeypatch.setenv('AIGIT_PROVENANCE_KEY', 'secret')
    _write_row(tmp_path)  # no signature field
    monkeypatch.setattr(core, '_run_git', _fake_git())
    monkeypatch.chdir(tmp_path)
    rc = core.cmd_verify_provenance(argparse.Namespace(ref='HEAD', require_signature=True))
    assert rc == 1
    assert 'not validly signed' in capsys.readouterr().err


def test_require_signature_accepts_valid(tmp_path, monkeypatch):
    monkeypatch.setenv('AIGIT_PROVENANCE_KEY', 'secret')
    sig = core._provenance_signature('secret', COMMIT, 'codex', 'gpt-5.4', PROMPT_HASH)
    _write_row(tmp_path, signature=sig)
    monkeypatch.setattr(core, '_run_git', _fake_git())
    monkeypatch.chdir(tmp_path)
    rc = core.cmd_verify_provenance(argparse.Namespace(ref='HEAD', require_signature=True))
    assert rc == 0
