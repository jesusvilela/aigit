"""Tests for diff-time lineage recovery (move / rename / refactor)."""
from aigit.core import _simhash, _chunk_similarity, compute_semantic_diff


def _entry(sid, path, anchor, content_hash, fingerprint=''):
    return {
        sid: {
            'semantic_id': sid,
            'path': path,
            'anchor': anchor,
            'content_hash': content_hash,
            'fingerprint': fingerprint,
        }
    }


def test_simhash_is_deterministic_and_discriminating():
    body = 'def score(v):\n    return v * 2 + 7\n'
    assert _simhash(body) == _simhash(body)
    assert _simhash(body) != _simhash('def other():\n    return None\n')
    assert _simhash('') == '0' * 16


def test_chunk_similarity_exact_and_near():
    a = {'content_hash': 'H', 'fingerprint': 'aaaa'}
    b = {'content_hash': 'H', 'fingerprint': 'bbbb'}
    assert _chunk_similarity(a, b) == 1.0  # identical content wins outright
    near_a = {'content_hash': 'X', 'fingerprint': _simhash('def f(v):\n    return v * 2 + 7\n')}
    near_b = {'content_hash': 'Y', 'fingerprint': _simhash('def f(v):\n    return v * 2 + 7  # note\n')}
    far = {'content_hash': 'Z', 'fingerprint': _simhash('class Totally:\n    pass\n')}
    assert _chunk_similarity(near_a, near_b) >= 0.85
    assert _chunk_similarity(near_a, far) < 0.85


def test_move_and_rename_identical_body_is_lineage_not_add_remove():
    base = _entry('sc_old', 'aigit/mod_a.py', 'compute_score', 'HASH', 'FP')
    head = _entry('sc_new', 'aigit/mod_b.py', 'calculate_score', 'HASH', 'FP')
    result = compute_semantic_diff(base, head)
    assert result['added'] == []
    assert result['removed'] == []
    assert len(result['lineage']) == 1
    edge = result['lineage'][0]
    assert edge['kind'] == 'moved+renamed'
    assert edge['from'] == 'sc_old' and edge['to'] == 'sc_new'
    assert edge['similarity'] == 1.0


def test_pure_rename_same_file():
    base = _entry('sc_old', 'm.py', 'foo', 'H', 'FP')
    head = _entry('sc_new', 'm.py', 'bar', 'H', 'FP')
    (edge,) = compute_semantic_diff(base, head)['lineage']
    assert edge['kind'] == 'renamed'


def test_refactor_detected_via_fingerprint():
    fp_old = _simhash('def handler(req):\n    return process(req) + 1\n')
    fp_new = _simhash('def handler(req):\n    return process(req) + 1  # guard added\n')
    base = _entry('sc_old', 'h.py', 'handler', 'HOLD', fp_old)
    head = _entry('sc_new', 'h.py', 'handler_v2', 'HNEW', fp_new)
    (edge,) = compute_semantic_diff(base, head)['lineage']
    assert edge['kind'] == 'refactored'
    assert 0.85 <= edge['similarity'] < 1.0


def test_unrelated_add_and_remove_stay_separate():
    base = _entry('sc_a', 'm.py', 'alpha', 'HA', _simhash('def alpha():\n    return 1\n'))
    head = _entry('sc_b', 'm.py', 'beta', 'HB', _simhash('def beta(x, y, z):\n    return x*y*z - 99\n'))
    result = compute_semantic_diff(base, head)
    assert result['lineage'] == []
    assert len(result['added']) == 1 and len(result['removed']) == 1
