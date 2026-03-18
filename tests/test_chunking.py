from pathlib import Path

import argparse

from aigit.core import build_manifest, write_manifest, parse_json, parse_yaml, parse_typescript


def test_chunk_generation_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / 'sample.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    chunks1, edges1 = build_manifest(tmp_path)
    write_manifest(chunks1, edges1, tmp_path)
    chunks2, edges2 = build_manifest(tmp_path)
    assert [c.semantic_id for c in chunks1] == [c.semantic_id for c in chunks2]
    assert edges2 == []


def test_markdown_chunking(tmp_path: Path) -> None:
    (tmp_path / 'README.md').write_text('# One\nBody\n# Two\nNext\n', encoding='utf-8')
    chunks, _ = build_manifest(tmp_path)
    anchors = [c.anchor for c in chunks if c.path.endswith('README.md')]
    assert anchors == ['One', 'Two']


# ---------------------------------------------------------------------------
# Polyglot parser tests
# ---------------------------------------------------------------------------


def test_json_parser_object(tmp_path: Path) -> None:
    text = '{"name": "aigit", "version": "0.1.0"}'
    chunks = parse_json('pkg.json', text)
    anchors = [c.anchor for c in chunks]
    assert 'name' in anchors
    assert 'version' in anchors
    assert all(c.chunk_type == 'key' for c in chunks)


def test_json_parser_array(tmp_path: Path) -> None:
    text = '[1, 2, 3]'
    chunks = parse_json('arr.json', text)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == 'array'


def test_json_parser_empty_object(tmp_path: Path) -> None:
    # Empty object falls back to plain text chunking — should still return chunks
    chunks = parse_json('empty.json', '{}')
    assert len(chunks) >= 1


def test_json_parser_invalid_falls_back(tmp_path: Path) -> None:
    # Invalid JSON falls back gracefully without raising
    chunks = parse_json('bad.json', 'not valid json {{{')
    assert len(chunks) >= 1


def test_yaml_parser_top_level_keys(tmp_path: Path) -> None:
    text = 'version: 1\nparsers:\n  .py: python-ast\ndefault: file\n'
    chunks = parse_yaml('ruleset.yaml', text)
    anchors = [c.anchor for c in chunks]
    assert 'version' in anchors
    assert 'parsers' in anchors


def test_yaml_parser_empty_falls_back(tmp_path: Path) -> None:
    # Empty YAML shouldn't crash
    chunks = parse_yaml('empty.yaml', '')
    assert isinstance(chunks, list)


def test_typescript_parser_function(tmp_path: Path) -> None:
    text = 'export function greet(name: string): string {\n  return `Hello ${name}`;\n}\n'
    chunks = parse_typescript('greet.ts', text)
    anchors = [c.anchor for c in chunks]
    assert 'greet' in anchors


def test_typescript_parser_class(tmp_path: Path) -> None:
    text = 'export class MyService {\n  run() {}\n}\n'
    chunks = parse_typescript('service.ts', text)
    anchors = [c.anchor for c in chunks]
    assert 'MyService' in anchors
    assert any(c.chunk_type == 'class' for c in chunks)


def test_typescript_parser_interface(tmp_path: Path) -> None:
    text = 'export interface Config {\n  debug: boolean;\n}\n'
    chunks = parse_typescript('types.ts', text)
    anchors = [c.anchor for c in chunks]
    assert 'Config' in anchors
    assert any(c.chunk_type == 'interface' for c in chunks)


def test_typescript_parser_no_decls_falls_back(tmp_path: Path) -> None:
    # Plain text .ts file with no recognisable declarations
    chunks = parse_typescript('data.ts', 'const x = 1;\nconst y = 2;\n')
    assert len(chunks) >= 1


def test_json_chunking_via_build_manifest(tmp_path: Path) -> None:
    (tmp_path / 'config.json').write_text('{"host": "localhost", "port": 8080}', encoding='utf-8')
    chunks, _ = build_manifest(tmp_path)
    json_chunks = [c for c in chunks if c.path.endswith('config.json')]
    anchors = [c.anchor for c in json_chunks]
    assert 'host' in anchors
    assert 'port' in anchors


def test_yaml_chunking_via_build_manifest(tmp_path: Path) -> None:
    (tmp_path / 'config.yaml').write_text('name: myapp\nenv: production\n', encoding='utf-8')
    chunks, _ = build_manifest(tmp_path)
    yaml_chunks = [c for c in chunks if c.path.endswith('config.yaml')]
    anchors = [c.anchor for c in yaml_chunks]
    assert 'name' in anchors
    assert 'env' in anchors


def test_typescript_chunking_via_build_manifest(tmp_path: Path) -> None:
    (tmp_path / 'app.ts').write_text(
        'export class App {\n  start() {}\n}\nexport function main() {}\n',
        encoding='utf-8',
    )
    chunks, _ = build_manifest(tmp_path)
    ts_chunks = [c for c in chunks if c.path.endswith('app.ts')]
    anchors = [c.anchor for c in ts_chunks]
    assert 'App' in anchors or 'main' in anchors


# ---------------------------------------------------------------------------
# cmd_improve tests
# ---------------------------------------------------------------------------


def test_cmd_improve_passes(tmp_path: Path) -> None:
    from aigit.core import cmd_improve

    (tmp_path / 'sample.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    ns = argparse.Namespace(repo=str(tmp_path), test_path='')
    # Improve runs pytest; in test environments there is no test/ dir in tmp_path
    # so pytest exits 0 (no tests collected is still exit code 5 — we accept nonzero
    # from pytest itself but we should not crash).
    rc = cmd_improve(ns)
    assert rc in (0, 5)  # 0 = passed, 5 = no tests collected


# ---------------------------------------------------------------------------
# cmd_setup_storage tests
# ---------------------------------------------------------------------------


def test_cmd_setup_storage_git_backend(tmp_path: Path) -> None:
    """Switching to plain git backend should not crash and should remove LFS entries."""
    from aigit.core import cmd_setup_storage

    # Pre-populate .gitattributes with an LFS entry
    ga = tmp_path / '.gitattributes'
    ga.write_text('.semantic/manifest.jsonl filter=lfs diff=lfs merge=lfs -text\n', encoding='utf-8')

    ns = argparse.Namespace(backend='git', repo=str(tmp_path))
    rc = cmd_setup_storage(ns)
    assert rc == 0
    # The LFS entry should have been removed
    content = ga.read_text(encoding='utf-8')
    assert 'manifest.jsonl' not in content


def test_cmd_setup_storage_lfs_no_lfs_binary(tmp_path: Path, monkeypatch) -> None:
    """When git-lfs is absent, the lfs backend should return exit code 1."""
    from aigit.core import cmd_setup_storage, _probe_git_lfs

    monkeypatch.setattr('aigit.core._probe_git_lfs', lambda: False)
    ns = argparse.Namespace(backend='lfs', repo=str(tmp_path))
    rc = cmd_setup_storage(ns)
    assert rc == 1


def test_setup_storage_lfs_writes_gitattributes(tmp_path: Path, monkeypatch) -> None:
    """When git-lfs is present, .gitattributes should be written with patterns."""
    from unittest.mock import MagicMock
    from aigit.core import cmd_setup_storage

    monkeypatch.setattr('aigit.core._probe_git_lfs', lambda: True)
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr('aigit.core.subprocess.run', fake_run)
    ns = argparse.Namespace(backend='lfs', repo=str(tmp_path))
    rc = cmd_setup_storage(ns)
    assert rc == 0
    ga = tmp_path / '.gitattributes'
    assert ga.exists()
    content = ga.read_text(encoding='utf-8')
    assert 'manifest.jsonl' in content
    assert 'filter=lfs' in content

