"""Incremental chunk cache must be transparent: identical output to a full rebuild."""
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
