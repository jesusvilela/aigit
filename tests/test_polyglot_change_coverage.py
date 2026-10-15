"""Behavior-changing edits must survive parser, diff, cache, and Git-ref paths."""
import json
import os
import stat
import subprocess

import pytest

from aigit import core


def _records(chunks):
    return {c.semantic_id: c.to_dict() for c in chunks}


@pytest.mark.parametrize('before,after', [
    ('export function add(x: number) {\n  return x + 1;\n}\n',
     'export function add(x: number) {\n  return x + 2;\n}\n'),
    ('export class App {\n  start() { return 1; }\n}\n',
     'export class App {\n  start() { return 2; }\n}\n'),
    ('export interface Config {\n  port: number;\n}\n',
     'export interface Config {\n  port: string;\n}\n'),
    ('export type Config = {\n  enabled: boolean;\n};\n',
     'export type Config = {\n  enabled: string;\n};\n'),
    ('export const add = (x: number) => {\n  return x + 1;\n};\n',
     'export const add = (x: number) => {\n  return x + 2;\n};\n'),
])
def test_typescript_body_edits_are_changed(before, after):
    base = _records(core.parse_typescript('sample.ts', before))
    head = _records(core.parse_typescript('sample.ts', after))
    diff = core.compute_semantic_diff(base, head)
    assert len(diff['changed']) == 1
    assert not diff['added'] and not diff['removed']


def test_typescript_sections_do_not_mark_adjacent_declaration_changed():
    text = 'export function a() {\n  return 1;\n}\nexport function b() {\n  return 2;\n}\n'
    base = core.parse_typescript('a.ts', text)
    head = core.parse_typescript('a.ts', text.replace('return 2', 'return 3'))
    assert [(c.anchor, c.start_line, c.end_line) for c in base] == [('a', 1, 3), ('b', 4, 6)]
    assert base[0].content_hash == head[0].content_hash
    assert base[1].content_hash != head[1].content_hash


def test_typescript_ignores_fake_declarations_in_literals_comments_and_nested_code():
    text = ('const banner = `\nexport function fake() {}\n`;\n'
            '/*\nexport class Fake {}\n*/\n'
            'export function outer() {\nfunction nested() {}\nreturn /[{}]/;\n}\n'
            'export default class Real {}\n')
    chunks = core.parse_typescript('sample.ts', text)
    assert [c.anchor for c in chunks if c.chunk_type != 'file'] == ['outer', 'Real']
    assert core.parse_typescript('sample.ts', text.replace('Fake', 'Changed')) != chunks


def test_typescript_division_preserves_declaration_ids_and_independent_edits():
    text = ('export function f(a: number, b: number, c: number) {\n'
            '  return a / (b / c);\n}\n'
            'export function g() {\n  return /[{}]/.test("{}");\n}\n')
    base = core.parse_typescript('sample.ts', text)
    ours = core.parse_typescript('sample.ts', text.replace('a / (b / c)', 'a / (b / (c + 1))'))
    theirs = core.parse_typescript('sample.ts', text.replace('.test("{}")', '.test("{ }")'))
    assert [c.anchor for c in base] == ['f', 'g']
    assert [c.semantic_id for c in base] == [c.semantic_id for c in ours] == [c.semantic_id for c in theirs]
    assert core.compute_semantic_conflicts(_records(base), _records(ours), _records(theirs)) == []


@pytest.mark.parametrize('before,after', [
    ('server:\n  port: 80\n', 'server:\n  port: 81\n'),
    ('items:\n  - first\n  - second\n', 'items:\n  - first\n  - third\n'),
    ('message: |\n  hello\n  world\n', 'message: |\n  hello\n  there\n'),
    ('server: {port: 80}\n', 'server: {port: 81}\n'),
    ('"http:port":\n  value: 80\n', '"http:port":\n  value: 81\n'),
])
def test_yaml_value_edits_are_changed(before, after):
    base = _records(core.parse_yaml('config.yaml', before))
    head = _records(core.parse_yaml('config.yaml', after))
    assert len(core.compute_semantic_diff(base, head)['changed']) == 1


def test_yaml_sections_are_complete_and_independent():
    before = 'server:\n  port: 80\nitems:\n  - one\n  - two\n'
    base = core.parse_yaml('config.yaml', before)
    head = core.parse_yaml('config.yaml', before.replace('two', 'three'))
    assert [(c.anchor, c.start_line, c.end_line) for c in base] == [('server', 1, 2), ('items', 3, 5)]
    assert base[0].content_hash == head[0].content_hash
    assert base[1].content_hash != head[1].content_hash


@pytest.mark.parametrize('name,before,after', [
    ('sample.ts', 'export function f() {\n  return 1;\n}\n', 'export function f() {\n  return 2;\n}\n'),
    ('config.yaml', 'server:\n  port: 80\n', 'server:\n  port: 81\n'),
])
def test_real_git_diff_conflict_and_incremental_paths(tmp_path, monkeypatch, name, before, after):
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, text=True, capture_output=True, check=True).stdout.strip()

    git('init', '-q', '--template=')
    git('config', 'user.name', 'regression')
    git('config', 'user.email', 'regression@localhost')
    git('config', 'commit.gpgsign', 'false')
    src = tmp_path / name
    src.write_text(before, encoding='utf-8')
    initial, edges = core.build_manifest(tmp_path)
    core.write_manifest(initial, edges, tmp_path)
    git('add', '.')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    # A cache in the old parser schema must be ignored even for unchanged bytes.
    cache_path = tmp_path / core.CHUNK_CACHE_FILE
    stale = json.loads(cache_path.read_text(encoding='utf-8'))
    stale['version'] = '5'
    for entry in stale['files'].values():
        for c in entry['chunks']:
            c['content_hash'] = 'obsolete-declaration-only'
    cache_path.write_text(json.dumps(stale), encoding='utf-8')
    rebuilt, _ = core.build_manifest(tmp_path)
    assert [c.to_dict() for c in rebuilt] == [c.to_dict() for c in initial]
    src.write_text(after, encoding='utf-8')
    updated, edges = core.build_manifest(tmp_path)
    core.write_manifest(updated, edges, tmp_path)
    git('add', '.')
    git('commit', '-qm', 'head')
    monkeypatch.chdir(tmp_path)
    diff = core.compute_semantic_diff(core._read_manifest_from_ref(base), core._read_manifest_from_ref('HEAD'))
    assert len(diff['changed']) == 1
    third_text = after.replace('2', '3') if name.endswith('.ts') else after.replace('81', '82')
    src.write_text(third_text, encoding='utf-8')
    third, _ = core.build_manifest(tmp_path)
    assert [c['kind'] for c in core.compute_semantic_conflicts(_records(initial), _records(updated), _records(third))] == ['modify/modify']


def test_failed_manifest_publication_preserves_existing_file(tmp_path, monkeypatch):
    (tmp_path / 'sample.py').write_text('def f():\n    return 1\n', encoding='utf-8')
    chunks, edges = core.build_manifest(tmp_path)
    core.write_manifest(chunks, edges, tmp_path)
    manifest = tmp_path / core.MANIFEST_FILE
    original = manifest.read_bytes()

    def failed_replace(*args):
        raise OSError('injected publication failure')

    monkeypatch.setattr(core.os, 'replace', failed_replace)
    with pytest.raises(OSError, match='injected publication failure'):
        core.write_manifest([], [], tmp_path)
    assert manifest.read_bytes() == original
    assert not list(manifest.parent.glob('.*.tmp'))


@pytest.mark.skipif(os.name == 'nt', reason='POSIX group/other mode bits are unavailable on Windows')
def test_atomic_manifest_publication_preserves_permissions(tmp_path):
    (tmp_path / 'sample.py').write_text('x = 1\n', encoding='utf-8')
    chunks, edges = core.build_manifest(tmp_path)
    core.write_manifest(chunks, edges, tmp_path)
    manifest = tmp_path / core.MANIFEST_FILE
    manifest.chmod(0o640)
    core.write_manifest(chunks, edges, tmp_path)
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o640
