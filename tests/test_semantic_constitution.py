import json
from pathlib import Path

from aigit.core import (
    BUILD_CONTEXT_FILE,
    CHUNK_CACHE_FILE,
    build_manifest,
    ensure_semantic_scaffold,
)


def _records(chunks):
    return [chunk.to_dict() for chunk in chunks]


def test_ruleset_controls_parser_dispatch_and_invalidates_cache(tmp_path: Path) -> None:
    ensure_semantic_scaffold(tmp_path)
    source = tmp_path / 'guide.md'
    source.write_text('# One\nBody\n# Two\nMore\n', encoding='utf-8')

    heading_chunks, _ = build_manifest(tmp_path)
    assert [chunk.anchor for chunk in heading_chunks] == ['One', 'Two']

    ruleset = tmp_path / '.semantic/ruleset.yaml'
    ruleset.write_text(
        ruleset.read_text(encoding='utf-8').replace(
            '  .md: markdown-headings', '  .md: file'
        ),
        encoding='utf-8',
    )
    file_chunks, _ = build_manifest(tmp_path)

    assert len(file_chunks) == 1
    assert file_chunks[0].chunk_type == 'file'
    cache = json.loads((tmp_path / CHUNK_CACHE_FILE).read_text(encoding='utf-8'))
    assert cache['files']['guide.md']['chunks'][0]['chunk_type'] == 'file'


def test_canonical_graph_ignores_foreign_previous_index(tmp_path: Path) -> None:
    (tmp_path / 'module.py').write_text('def stable():\n    return 1\n', encoding='utf-8')
    first, _ = build_manifest(tmp_path)
    index = tmp_path / '.semantic/chunk_index.json'
    index.write_text(
        json.dumps(
            {
                'module.py::function::stable': {
                    **first[0].to_dict(),
                    'semantic_id': 'sc_poisoned',
                }
            }
        ),
        encoding='utf-8',
    )

    second, edges = build_manifest(tmp_path)

    assert _records(second) == _records(first)
    assert second[0].semantic_id != 'sc_poisoned'
    assert edges == []


def test_declared_text_representations_have_same_semantics(tmp_path: Path) -> None:
    source = tmp_path / 'module.py'
    source.write_bytes(b'def stable():  \r\n    return 1\t\r\n')
    crlf_chunks, _ = build_manifest(tmp_path)
    (tmp_path / CHUNK_CACHE_FILE).unlink()
    source.write_text('def stable():\n    return 1\n', encoding='utf-8')
    lf_chunks, _ = build_manifest(tmp_path)

    assert _records(crlf_chunks) == _records(lf_chunks)


def test_build_context_records_semantic_constitution(tmp_path: Path) -> None:
    from aigit.core import write_manifest

    (tmp_path / 'notes.txt').write_text('intent\n', encoding='utf-8')
    chunks, edges = build_manifest(tmp_path)
    write_manifest(chunks, edges, tmp_path)

    context = json.loads((tmp_path / BUILD_CONTEXT_FILE).read_text(encoding='utf-8'))
    assert set(context) == {
        'aigit_version',
        'canonicalizer_version',
        'parser_registry_digest',
        'ruleset_digest',
        'semantic_schema',
    }
    assert len(context['ruleset_digest']) == 64
