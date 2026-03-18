from pathlib import Path

from aigit.core import build_manifest, write_manifest


def test_chunk_generation_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / 'sample.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    chunks1, edges1 = build_manifest(tmp_path)
    write_manifest(chunks1, edges1)
    write_manifest(chunks1, edges1, tmp_path)
    chunks2, edges2 = build_manifest(tmp_path)
    assert [c.semantic_id for c in chunks1] == [c.semantic_id for c in chunks2]
    assert edges2 == []


def test_markdown_chunking(tmp_path: Path) -> None:
    (tmp_path / 'README.md').write_text('# One\nBody\n# Two\nNext\n', encoding='utf-8')
    chunks, _ = build_manifest(tmp_path)
    anchors = [c.anchor for c in chunks if c.path.endswith('README.md')]
    assert anchors == ['One', 'Two']
