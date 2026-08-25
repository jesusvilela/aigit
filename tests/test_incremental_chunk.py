"""Incremental chunk cache must be transparent: identical output to a full rebuild."""
import json
from pathlib import Path

from aigit.core import build_manifest, CHUNK_CACHE_FILE


def _dicts(chunks):
    return [c.to_dict() for c in chunks]


def _seed(tmp_path):
    (tmp_path / 'a.py').write_text('def a():\n    return 1\n', encoding='utf-8')
    (tmp_path / 'b.py').write_text('class B:\n    pass\n', encoding='utf-8')
    (tmp_path / 'doc.md').write_text('# Title\n\nbody\n', encoding='utf-8')


def test_cache_is_created_and_idempotent(tmp_path):
    _seed(tmp_path)
    first, _ = build_manifest(tmp_path)
    assert (tmp_path / CHUNK_CACHE_FILE).exists()
    second, _ = build_manifest(tmp_path)  # served from cache
    assert _dicts(first) == _dicts(second)


def test_incremental_matches_full_rebuild_after_edit(tmp_path):
    _seed(tmp_path)
    build_manifest(tmp_path)  # warm cache
    (tmp_path / 'a.py').write_text('def a():\n    return 1\n\n\ndef c():\n    return 3\n', encoding='utf-8')
    incremental, _ = build_manifest(tmp_path)  # partial cache hit
    # full rebuild from scratch (no cache)
    (tmp_path / CHUNK_CACHE_FILE).unlink()
    full, _ = build_manifest(tmp_path)
    assert _dicts(incremental) == _dicts(full)


def test_cached_parse_error_resurfaces_under_strict(tmp_path):
    (tmp_path / 'bad.py').write_text('def broken(:\n    return 1\n', encoding='utf-8')
    errors1: list = []
    build_manifest(tmp_path, errors1)
    assert any(e['path'] == 'bad.py' for e in errors1)
    # second run is a cache hit but the error must still surface (gates stay honest)
    errors2: list = []
    build_manifest(tmp_path, errors2)
    assert any(e['path'] == 'bad.py' for e in errors2)


def test_cache_from_an_older_schema_is_ignored(tmp_path: Path) -> None:
    """A cache written before a Chunk field existed must not be reused.

    Entries are rehydrated with ``Chunk(**record)``, so a stale one backfills
    new fields with their defaults -- which shows up as a manifest that differs
    from a clean rebuild, and as silently degraded matching.
    """
    (tmp_path / 'sample.py').write_text(
        'def pick(model):\n    return model\n', encoding='utf-8'
    )
    chunks, _ = build_manifest(tmp_path)
    assert all(c.body_fingerprint for c in chunks if c.chunk_type == 'function')

    cache_path = tmp_path / CHUNK_CACHE_FILE
    stale = json.loads(cache_path.read_text(encoding='utf-8'))
    stale['version'] = '0'
    for entry in stale['files'].values():
        for record in entry.get('chunks', []):
            record.pop('body_fingerprint', None)
    cache_path.write_text(json.dumps(stale), encoding='utf-8')

    rebuilt, _ = build_manifest(tmp_path)
    assert all(c.body_fingerprint for c in rebuilt if c.chunk_type == 'function')
    assert [c.to_dict() for c in rebuilt] == [c.to_dict() for c in chunks]


def test_every_function_chunk_carries_a_body_fingerprint(tmp_path: Path) -> None:
    """Guards the failure mode directly: an empty body_fingerprint silently
    drops duplicate-work back to name-inclusive matching."""
    (tmp_path / 'm.py').write_text(
        'def a(x):\n    return x + 1\n\n\nclass B:\n    pass\n', encoding='utf-8'
    )
    chunks, _ = build_manifest(tmp_path)
    code = [c for c in chunks if c.chunk_type in ('function', 'class')]
    assert code and all(c.body_fingerprint for c in code)
