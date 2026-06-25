"""Tests for serve-api filter/pagination helper."""
from aigit.core import _filter_paginate


def _chunks():
    return [{'path': f'a/{i}.py', 'anchor': f'f{i}'} for i in range(10)] + [
        {'path': 'b/x.py', 'anchor': 'g'}
    ]


def test_no_filter_returns_all():
    page, total = _filter_paginate(_chunks())
    assert total == 11 and len(page) == 11


def test_limit_and_offset():
    page, total = _filter_paginate(_chunks(), limit=5)
    assert len(page) == 5 and total == 11
    page, total = _filter_paginate(_chunks(), offset=8, limit=5)
    assert len(page) == 3  # items[8:13] of 11
    assert total == 11


def test_path_prefix_filter():
    page, total = _filter_paginate(_chunks(), path_prefix='a/')
    assert total == 10 and all(c['path'].startswith('a/') for c in page)
    page, total = _filter_paginate(_chunks(), path_prefix='a/', limit=3)
    assert len(page) == 3 and total == 10


def test_negative_offset_clamped():
    page, total = _filter_paginate(_chunks(), offset=-5, limit=2)
    assert len(page) == 2
