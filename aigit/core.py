from __future__ import annotations

import argparse
import ast
import dataclasses
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

SEMANTIC_DIR = Path('.semantic')
MANIFEST_FILE = SEMANTIC_DIR / 'manifest.jsonl'
EDGES_FILE = SEMANTIC_DIR / 'edges.jsonl'
INDEX_FILE = SEMANTIC_DIR / 'chunk_index.json'
RULESET_FILE = SEMANTIC_DIR / 'ruleset.yaml'
SCHEMA_FILE = SEMANTIC_DIR / 'schema_version'

SUPPORTED_PARSER_BACKENDS = {'python-ast', 'markdown-headings', 'json-keys', 'yaml-keys', 'typescript-ast', 'file'}

DEERFLOW_VENDOR_DIR = Path('.deerflow/vendor/deer-flow')
DEERFLOW_VENDOR_ENV_FILE = DEERFLOW_VENDOR_DIR / '.env'
DEERFLOW_VENDOR_CONFIG_FILE = DEERFLOW_VENDOR_DIR / 'config.yaml'
DEERFLOW_VENDOR_RUNTIME_DIR = DEERFLOW_VENDOR_DIR / 'backend' / '.deer-flow'
DEERFLOW_VENDOR_AGENTS_DIR = DEERFLOW_VENDOR_RUNTIME_DIR / 'agents'
DEERFLOW_VENDOR_USER_PROFILE_FILE = DEERFLOW_VENDOR_RUNTIME_DIR / 'USER.md'
DEERFLOW_LAUNCH_SCRIPT = Path('scripts/run_deerflow.sh')
DEERFLOW_ENV_FILE = Path('.deerflow/.env.example')
DEERFLOW_RUNTIME_ENV_FILE = Path('.deerflow/.env')
DEERFLOW_CONFIG_FILE = Path('.deerflow/config.yaml')
DEERFLOW_AGENTS_DIR = Path('.deerflow/agents')
DEERFLOW_USER_PROFILE_FILE = Path('.deerflow/USER.md')
DEERFLOW_OBJECTIVES_DIR = Path('.deerflow/objectives')
DEERFLOW_QUEUE_FILE = Path('.deerflow/epic_queue.json')
DEERFLOW_EPIC_LAUNCH_SCRIPT = Path('scripts/run_deerflow_epics.sh')
DEERFLOW_RECOVERY_SCRIPT = Path('scripts/recover_deerflow.sh')
DEERFLOW_SYNC_METADATA = '.aigit-deerflow-sync.json'
DEERFLOW_DEFAULT_WORKSPACE_SUBDIR = 'repo'
EPICS_DIR = Path('docs/epics')
ROADMAP_FILE = Path('docs/EPICS_ROADMAP.md')
TASKS_FILE = Path('docs/MULTISOTA_CODEX_TASKS.md')
AIGIT_RUNTIME_DIR = Path('.aigit/runtime')

DEERFLOW_THREAD_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')
DEERFLOW_SYNC_SKIP_NAMES = {
    '__pycache__',
    '.cache',
    '.hypothesis',
    '.mypy_cache',
    '.nox',
    '.pytest_cache',
    '.ruff_cache',
    '.tox',
    '.venv',
    'node_modules',
}

SCOUT_SKIP_DIRS = {
    '.git',
    '.venv',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '__pycache__',
    'node_modules',
}


@dataclasses.dataclass(frozen=True)
class EpicSpec:
    epic_id: str
    title: str
    source_file: Path
    goal: str
    deliverables: list[str]
    acceptance: str

@dataclasses.dataclass
class Chunk:
    semantic_id: str
    path: str
    chunk_type: str
    anchor: str
    content_hash: str
    start_line: int
    end_line: int
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class DeerFlowRepoSyncReport:
    thread_id: str
    host_workspace: Path
    sandbox_workspace: str
    files_copied: int
    symlinks_copied: int
    metadata_file: Path | None = None


@dataclasses.dataclass(frozen=True)
class RepoScoutSummary:
    repo_root: Path
    file_count: int
    python_file_count: int
    markdown_file_count: int
    test_file_count: int
    total_bytes: int
    largest_files: list[tuple[str, int]]
    recommended_tool: str
    recommended_interfaces: list[str]


def deerflow_live_repo_mount_path(repo_root: Path | None = None) -> str:
    root = repo_root.resolve() if repo_root is not None else Path.cwd().resolve()
    return root.as_posix()


def canonicalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace('\r\n', '\n').split('\n')]
    normalized = '\n'.join(lines).strip() + '\n'
    return normalized


def _hash(parts: list[str]) -> str:
    return hashlib.sha256('||'.join(parts).encode('utf-8')).hexdigest()


def _chunk_id(path: str, anchor: str, chunk_type: str) -> str:
    return f"sc_{_hash([path, anchor, chunk_type])[:16]}"


def _content_hash(text: str) -> str:
    return _hash([canonicalize_text(text)])


def parse_python(path: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return chunks
    lines = text.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = getattr(node, 'lineno', 1)
            end = getattr(node, 'end_lineno', start)
            segment = '\n'.join(lines[start - 1 : end])
            chunk_type = type(node).__name__.replace('Def', '').lower()
            anchor = node.name
            chunks.append(
                Chunk(
                    semantic_id=_chunk_id(path, anchor, chunk_type),
                    path=path,
                    chunk_type=chunk_type,
                    anchor=anchor,
                    content_hash=_content_hash(segment),
                    start_line=start,
                    end_line=end,
                    confidence='high',
                )
            )
    return chunks


def parse_markdown(path: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    lines = text.splitlines()
    header_idxs = [i for i, line in enumerate(lines) if line.lstrip().startswith('#')]
    for idx, header_idx in enumerate(header_idxs):
        start = header_idx + 1
        end = header_idxs[idx + 1] if idx + 1 < len(header_idxs) else len(lines)
        segment_lines = lines[header_idx:end]
        header = lines[header_idx].lstrip('#').strip() or f'section-{idx + 1}'
        segment = '\n'.join(segment_lines)
        chunks.append(
            Chunk(
                semantic_id=_chunk_id(path, header, 'section'),
                path=path,
                chunk_type='section',
                anchor=header,
                content_hash=_content_hash(segment),
                start_line=start,
                end_line=end,
                confidence='high',
            )
        )
    if not chunks and lines:
        segment = '\n'.join(lines)
        chunks.append(
            Chunk(
                semantic_id=_chunk_id(path, 'document', 'document'),
                path=path,
                chunk_type='document',
                anchor='document',
                content_hash=_content_hash(segment),
                start_line=1,
                end_line=len(lines),
                confidence='medium',
            )
        )
    return chunks


def parse_text(path: str, text: str) -> list[Chunk]:
    line_count = len(text.splitlines())
    return [
        Chunk(
            semantic_id=_chunk_id(path, 'file', 'file'),
            path=path,
            chunk_type='file',
            anchor='file',
            content_hash=_content_hash(text),
            start_line=1,
            end_line=line_count,
            confidence='low',
        )
    ]


def parse_json(path: str, text: str) -> list[Chunk]:
    """Chunk a JSON file by top-level keys (objects) or index (arrays)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_text(path, text)
    lines = text.splitlines()
    line_count = len(lines)
    if isinstance(data, dict):
        if not data:
            return parse_text(path, text)
        chunks: list[Chunk] = []
        for key in data:
            anchor = str(key)
            chunks.append(
                Chunk(
                    semantic_id=_chunk_id(path, anchor, 'key'),
                    path=path,
                    chunk_type='key',
                    anchor=anchor,
                    content_hash=_content_hash(json.dumps(data[key], sort_keys=True)),
                    start_line=1,
                    end_line=line_count,
                    confidence='high',
                )
            )
        return chunks
    if isinstance(data, list):
        anchor = f'array[{len(data)}]'
        return [
            Chunk(
                semantic_id=_chunk_id(path, anchor, 'array'),
                path=path,
                chunk_type='array',
                anchor=anchor,
                content_hash=_content_hash(text),
                start_line=1,
                end_line=line_count,
                confidence='medium',
            )
        ]
    return parse_text(path, text)


def parse_yaml(path: str, text: str) -> list[Chunk]:
    """Chunk a YAML file by top-level keys via deterministic line scanning.

    We intentionally avoid dependency-specific parsing here so semantic output
    remains stable across environments where optional YAML libraries may or may
    not be installed.
    """
    lines = text.splitlines()
    # Top-level keys via line scanning (no-indent lines with a colon).
    chunks_fb: list[Chunk] = []
    for i, line in enumerate(lines, 1):
        if line and not line[0].isspace() and ':' in line and not line.lstrip().startswith('#'):
            key = line.split(':', 1)[0].strip()
            if key:
                chunks_fb.append(
                    Chunk(
                        semantic_id=_chunk_id(path, key, 'key'),
                        path=path,
                        chunk_type='key',
                        anchor=key,
                        content_hash=_content_hash(line),
                        start_line=i,
                        end_line=i,
                        confidence='medium',
                    )
                )
    return chunks_fb if chunks_fb else parse_text(path, text)


_TS_DECL_PATTERN = re.compile(
    r'^(?:export\s+)?(?:(?:async\s+)?function\*?\s+(\w+)|class\s+(\w+)|interface\s+(\w+)|type\s+(\w+)\s*=|(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s+)?\()',
    re.MULTILINE,
)


def parse_typescript(path: str, text: str) -> list[Chunk]:
    """Chunk a TypeScript/JavaScript file by top-level declarations."""
    lines = text.splitlines()
    line_count = len(lines)
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for match in _TS_DECL_PATTERN.finditer(text):
        name = next((g for g in match.groups() if g), None)
        if not name or name in seen:
            continue
        seen.add(name)
        start_line = text.count('\n', 0, match.start()) + 1
        chunk_type = 'function'
        raw = match.group(0)
        if 'class' in raw:
            chunk_type = 'class'
        elif 'interface' in raw:
            chunk_type = 'interface'
        elif raw.lstrip().startswith('type '):
            chunk_type = 'type'
        chunks.append(
            Chunk(
                semantic_id=_chunk_id(path, name, chunk_type),
                path=path,
                chunk_type=chunk_type,
                anchor=name,
                content_hash=_content_hash(match.group(0)),
                start_line=start_line,
                end_line=start_line,
                confidence='medium',
            )
        )
    return chunks if chunks else parse_text(path, text)


def parse_file(full_path: Path, rel_path: str) -> list[Chunk]:
    text = full_path.read_text(encoding='utf-8', errors='replace')
    suffix = full_path.suffix.lower()
    if suffix == '.py':
        return parse_python(rel_path, text)
    if suffix in {'.md', '.markdown'}:
        return parse_markdown(rel_path, text)
    if suffix == '.json':
        return parse_json(rel_path, text)
    if suffix in {'.yaml', '.yml'}:
        return parse_yaml(rel_path, text)
    if suffix in {'.ts', '.tsx'}:
        return parse_typescript(rel_path, text)
    return parse_text(rel_path, text)

def _repo_semantic_path(root: Path, path: Path) -> Path:
    return root / path


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    section_stack: list[tuple[int, dict[str, Any]]] = [(-1, parsed)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith('#'):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(' '))
        stripped = raw_line.strip()
        if ':' not in stripped:
            raise ValueError(f'unsupported ruleset syntax: {raw_line!r}')
        key, value = stripped.split(':', 1)
        key = key.strip()
        value = value.strip()

        while len(section_stack) > 1 and indent <= section_stack[-1][0]:
            section_stack.pop()
        current = section_stack[-1][1]

        if value:
            current[key] = value
            continue

        nested: dict[str, Any] = {}
        current[key] = nested
        section_stack.append((indent, nested))
    return parsed


def validate_ruleset_file(root: Path | None = None) -> dict[str, Any]:
    repo_root = root.resolve() if root is not None else Path('.').resolve()
    ensure_semantic_scaffold(repo_root)
    ruleset_file = _repo_semantic_path(repo_root, RULESET_FILE)
    parsed = _parse_simple_yaml(ruleset_file.read_text(encoding='utf-8'))
    parsers = parsed.get('parsers')
    if parsers is None:
        raise ValueError('ruleset must define a parsers mapping')
    if not isinstance(parsers, dict):
        raise ValueError('ruleset parsers must be a mapping')
    for suffix, backend in parsers.items():
        if not isinstance(backend, str) or backend not in SUPPORTED_PARSER_BACKENDS:
            raise ValueError(f'unsupported parser backend: {backend}')
        if suffix != 'default' and not suffix.startswith('.'):
            raise ValueError(f'invalid ruleset parser key: {suffix}')
    return parsed


def load_previous_index(root: Path) -> dict[str, dict[str, Any]]:
    index_file = _repo_semantic_path(root, INDEX_FILE)
    if not index_file.exists():
        return {}
    try:
        return json.loads(index_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def match_previous_id(chunk: Chunk, previous: dict[str, dict[str, Any]]) -> str:
    key = f"{chunk.path}::{chunk.chunk_type}::{chunk.anchor}"
    prev = previous.get(key)
    if not prev:
        return chunk.semantic_id
    prev_hash = prev.get('content_hash')
    if prev_hash == chunk.content_hash:
        return prev.get('semantic_id', chunk.semantic_id)
    similarity = difflib.SequenceMatcher(a=prev_hash or '', b=chunk.content_hash).ratio()
    if similarity >= 0.92:
        return prev.get('semantic_id', chunk.semantic_id)
    return chunk.semantic_id


def iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in {'.git', '.semantic', '.deerflow'}:
            continue
        if any(part == '__pycache__' or part.endswith('.egg-info') for part in rel.parts):
            continue
        if any(part.startswith('.') and part != '.github' for part in rel.parts):
            continue
        if path.suffix == '.pyc':
            continue
        files.append(rel)
    return sorted(files)


def ensure_semantic_scaffold(root: Path | None = None) -> None:
    root = root.resolve() if root is not None else Path('.').resolve()
    semantic_dir = _repo_semantic_path(root, SEMANTIC_DIR)
    schema_file = _repo_semantic_path(root, SCHEMA_FILE)
    ruleset_file = _repo_semantic_path(root, RULESET_FILE)
    semantic_dir.mkdir(exist_ok=True)
    (semantic_dir / 'cache').mkdir(exist_ok=True)
    if not schema_file.exists():
        schema_file.write_text('1\n', encoding='utf-8')
    if not ruleset_file.exists():
        ruleset_file.write_text(
            'version: 1\nparsers:\n  .py: python-ast\n  .md: markdown-headings\n  .json: json-keys\n  .yaml: yaml-keys\n  .yml: yaml-keys\n  .ts: typescript-ast\n  .tsx: typescript-ast\n  default: file\n',
            encoding='utf-8',
        )


def build_manifest(root: Path) -> tuple[list[Chunk], list[dict[str, Any]]]:
    ensure_semantic_scaffold(root)
    previous = load_previous_index(root)
    chunks: list[Chunk] = []
    edges: list[dict[str, Any]] = []
    for rel in iter_repo_files(root):
        parsed = parse_file(root / rel, str(rel))
        for chunk in parsed:
            old_id = match_previous_id(chunk, previous)
            if old_id != chunk.semantic_id:
                edges.append({'from': old_id, 'to': chunk.semantic_id, 'reason': 'refined-anchor'})
            chunk.semantic_id = old_id
            chunks.append(chunk)
    return chunks, edges


def write_manifest(chunks: list[Chunk], edges: list[dict[str, Any]], root: Path = Path('.')) -> None:
    manifest_file = _repo_semantic_path(root, MANIFEST_FILE)
    edges_file = _repo_semantic_path(root, EDGES_FILE)
    index_file = _repo_semantic_path(root, INDEX_FILE)
    manifest_lines = [json.dumps(chunk.to_dict(), sort_keys=True) for chunk in chunks]
    manifest_file.write_text('\n'.join(manifest_lines) + ('\n' if manifest_lines else ''), encoding='utf-8')
    edge_lines = [json.dumps(edge, sort_keys=True) for edge in edges]
    edges_file.write_text('\n'.join(edge_lines) + ('\n' if edge_lines else ''), encoding='utf-8')
    index: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        key = f"{chunk.path}::{chunk.chunk_type}::{chunk.anchor}"
        index[key] = chunk.to_dict()
    index_file.write_text(json.dumps(index, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def cmd_chunk(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    chunks, edges = build_manifest(repo_root)
    write_manifest(chunks, edges, repo_root)
    print(f"wrote {len(chunks)} chunks and {len(edges)} lineage edges")
    return 0


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(['git', *args], cwd=cwd, check=True, text=True, capture_output=True)
    return proc.stdout.strip()


def _read_manifest_from_ref(ref: str) -> dict[str, dict[str, Any]]:
    raw = _run_git(['show', f'{ref}:.semantic/manifest.jsonl'])
    out: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row['semantic_id']] = row
    return out


def cmd_diff(args: argparse.Namespace) -> int:
    base = _read_manifest_from_ref(args.base)
    head = _read_manifest_from_ref(args.head)
    added = [v for k, v in head.items() if k not in base]
    removed = [v for k, v in base.items() if k not in head]
    changed = [
        head[k]
        for k in set(base).intersection(head)
        if base[k].get('content_hash') != head[k].get('content_hash')
    ]
    report = [
        '# Semantic Diff Report',
        f'- Base: `{args.base}`',
        f'- Head: `{args.head}`',
        f'- Added: {len(added)}',
        f'- Removed: {len(removed)}',
        f'- Changed: {len(changed)}',
        '',
    ]
    for label, items in [('Added', added), ('Removed', removed), ('Changed', changed)]:
        report.append(f'## {label}')
        if not items:
            report.append('- None')
        else:
            for item in items:
                report.append(f"- `{item['semantic_id']}` {item['path']}::{item['anchor']}")
        report.append('')
    Path(args.output).write_text('\n'.join(report), encoding='utf-8')
    print(f'wrote {args.output}')
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    base = _read_manifest_from_ref(args.base)
    ours = _read_manifest_from_ref(args.ours)
    theirs = _read_manifest_from_ref(args.theirs)
    conflicts = []
    for sid, b in base.items():
        o = ours.get(sid)
        t = theirs.get(sid)
        if not o or not t:
            continue
        if o['content_hash'] != b['content_hash'] and t['content_hash'] != b['content_hash'] and o['content_hash'] != t['content_hash']:
            conflicts.append(sid)
    out = {'base': args.base, 'ours': args.ours, 'theirs': args.theirs, 'conflicts': conflicts}
    Path(args.output).write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print(f'detected {len(conflicts)} semantic conflicts')
    return 0


def cmd_record_provenance(args: argparse.Namespace) -> int:
    repo_root = Path('.').resolve()
    ensure_semantic_scaffold(repo_root)
    commit = _run_git(['rev-parse', 'HEAD'])
    row = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'commit': commit,
        'agent': args.agent,
        'model': args.model,
        'prompt_hash': _hash([args.prompt]),
    }
    path = _repo_semantic_path(repo_root, SEMANTIC_DIR / 'provenance.jsonl')
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, sort_keys=True) + '\n')
    print(f'appended provenance to {path}')
    return 0


def _parse_provenance_trailer(message: str) -> dict[str, str] | None:
    trailer_line = None
    for line in reversed(message.splitlines()):
        if line.startswith('AI-Provenance: '):
            trailer_line = line[len('AI-Provenance: ') :]
            break
    if trailer_line is None:
        return None
    fields: dict[str, str] = {}
    for part in trailer_line.split(';'):
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        fields[key.strip()] = value.strip()
    return fields or None


def verify_provenance(ref: str = 'HEAD', repo_root: Path = Path('.')) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    commit = _run_git(['rev-parse', ref], cwd=repo_root)
    message = _run_git(['show', '-s', '--format=%B', commit], cwd=repo_root)
    trailer = _parse_provenance_trailer(message)
    if trailer is None:
        raise ValueError(f'{commit} is missing an AI-Provenance trailer')

    provenance_path = _repo_semantic_path(repo_root, SEMANTIC_DIR / 'provenance.jsonl')
    rows = _read_jsonl_rows(provenance_path)
    matching_row = next((row for row in reversed(rows) if row.get('commit') == commit), None)
    if matching_row is None:
        raise ValueError(f'no provenance log row found for commit {commit}')

    prompt_hash = str(matching_row.get('prompt_hash', ''))
    trailer_prompt_hash = trailer.get('prompt-hash', '')
    if trailer_prompt_hash and not prompt_hash.startswith(trailer_prompt_hash):
        raise ValueError(f'provenance trailer does not match log row for commit {commit}')

    return {
        'commit': commit,
        'trailer': trailer,
        'log_row': matching_row,
        'provenance_path': str(provenance_path),
    }


def cmd_verify_provenance(args: argparse.Namespace) -> int:
    try:
        result = verify_provenance(ref=args.ref, repo_root=Path('.'))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    trailer = f"AI-Provenance: agent={args.agent};model={args.model};prompt-hash={_hash([args.prompt])[:16]}"
    message = f"{args.message}\n\n{trailer}\n"
    subprocess.run(['git', 'commit', '-m', message], check=True)
    return 0


def _write_file_if_missing(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding='utf-8')


def _write_deerflow_agent_if_missing(name: str, config_yaml: str, soul_md: str) -> None:
    agent_dir = DEERFLOW_AGENTS_DIR / name
    _write_file_if_missing(agent_dir / 'config.yaml', config_yaml)
    _write_file_if_missing(agent_dir / 'SOUL.md', soul_md)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _merge_env_defaults(target_text: str, template_text: str) -> str:
    existing_keys: set[str] = set()
    merged_lines = target_text.splitlines()
    for raw_line in merged_lines:
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _value = line.split('=', 1)
        existing_keys.add(key.strip())

    missing_lines: list[str] = []
    for raw_line in template_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _value = line.split('=', 1)
        normalized = key.strip()
        if normalized in existing_keys:
            continue
        missing_lines.append(f'{normalized}=')
        existing_keys.add(normalized)

    combined = merged_lines[:]
    if missing_lines:
        if combined and combined[-1].strip():
            combined.append('')
        combined.extend(missing_lines)
    return '\n'.join(combined).rstrip() + '\n'


def ensure_deerflow_runtime_env() -> bool:
    if not DEERFLOW_ENV_FILE.exists():
        return False
    template_text = DEERFLOW_ENV_FILE.read_text(encoding='utf-8')
    if DEERFLOW_RUNTIME_ENV_FILE.exists():
        merged = _merge_env_defaults(DEERFLOW_RUNTIME_ENV_FILE.read_text(encoding='utf-8'), template_text)
        if DEERFLOW_RUNTIME_ENV_FILE.read_text(encoding='utf-8') != merged:
            DEERFLOW_RUNTIME_ENV_FILE.write_text(merged, encoding='utf-8')
            return True
        return False
    DEERFLOW_RUNTIME_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEERFLOW_RUNTIME_ENV_FILE.write_text(template_text, encoding='utf-8')
    return True


def missing_deerflow_env_keys(required: tuple[str, ...] = ('OPENAI_API_KEY',)) -> list[str]:
    env = _parse_env_file(DEERFLOW_RUNTIME_ENV_FILE)
    return [key for key in required if not env.get(key)]


def _runtime_file(service_name: str, suffix: str) -> Path:
    return AIGIT_RUNTIME_DIR / f'{service_name}.{suffix}'


def _service_is_healthy(url: str, timeout: float = 2.5) -> bool:
    try:
        with urllib_request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def _read_service_pid(service_name: str, repo_root: Path) -> int | None:
    pid_file = (repo_root / _runtime_file(service_name, 'pid')).resolve()
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding='utf-8').strip())
    except ValueError:
        return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_service(url: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    while time.monotonic() < deadline:
        if _service_is_healthy(url):
            return True
        time.sleep(1)
    return _service_is_healthy(url)


def _spawn_detached_python_service(service_name: str, repo_root: Path, args: list[str]) -> tuple[int, Path]:
    runtime_dir = (repo_root / AIGIT_RUNTIME_DIR).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = (repo_root / _runtime_file(service_name, 'log')).resolve()
    pid_path = (repo_root / _runtime_file(service_name, 'pid')).resolve()

    with log_path.open('a', encoding='utf-8') as log_handle:
        process = subprocess.Popen(
            [sys.executable, '-m', 'aigit.cli', *args],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    pid_path.write_text(f'{process.pid}\n', encoding='utf-8')
    return process.pid, log_path


def _ensure_background_service(
    service_name: str,
    repo_root: Path,
    health_url: str,
    cli_args: list[str],
    startup_timeout: float,
) -> tuple[bool, str]:
    if _service_is_healthy(health_url):
        return True, f'{service_name} already healthy at {health_url}'

    pid = _read_service_pid(service_name, repo_root)
    log_path = (repo_root / _runtime_file(service_name, 'log')).resolve()
    if pid is not None and _pid_is_running(pid):
        if _wait_for_service(health_url, startup_timeout):
            return True, f'{service_name} became healthy at {health_url} (pid {pid})'
        return False, f'{service_name} is still running but not healthy; inspect {log_path}'

    pid, log_path = _spawn_detached_python_service(service_name, repo_root, cli_args)
    if _wait_for_service(health_url, startup_timeout):
        return True, f'started {service_name} at {health_url} (pid {pid}, log {log_path})'
    return False, f'started {service_name} but it did not become healthy; inspect {log_path}'


def _validate_deerflow_thread_id(thread_id: str) -> str:
    if not DEERFLOW_THREAD_ID_PATTERN.match(thread_id):
        raise ValueError('thread id must contain only letters, numbers, hyphens, or underscores')
    return thread_id


def _normalize_workspace_subdir(workspace_subdir: str) -> str:
    normalized = workspace_subdir.strip().strip('/')
    if not normalized:
        return ''
    path = Path(normalized)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in path.parts):
        raise ValueError('workspace subdir must be a relative path without "." or ".." segments')
    return path.as_posix()


def deerflow_threads_dir() -> Path:
    return (DEERFLOW_VENDOR_DIR / 'backend' / '.deer-flow' / 'threads').resolve()


def deerflow_thread_dir(thread_id: str) -> Path:
    return deerflow_threads_dir() / _validate_deerflow_thread_id(thread_id)


def deerflow_thread_workspace_dir(thread_id: str) -> Path:
    return deerflow_thread_dir(thread_id) / 'user-data' / 'workspace'


def deerflow_thread_uploads_dir(thread_id: str) -> Path:
    return deerflow_thread_dir(thread_id) / 'user-data' / 'uploads'


def deerflow_thread_outputs_dir(thread_id: str) -> Path:
    return deerflow_thread_dir(thread_id) / 'user-data' / 'outputs'


def deerflow_repo_workspace_dir(thread_id: str, workspace_subdir: str = DEERFLOW_DEFAULT_WORKSPACE_SUBDIR) -> Path:
    subdir = _normalize_workspace_subdir(workspace_subdir)
    workspace_root = deerflow_thread_workspace_dir(thread_id)
    return workspace_root if not subdir else workspace_root / subdir


def deerflow_sandbox_repo_path(workspace_subdir: str = DEERFLOW_DEFAULT_WORKSPACE_SUBDIR) -> str:
    subdir = _normalize_workspace_subdir(workspace_subdir)
    return '/mnt/user-data/workspace' if not subdir else f'/mnt/user-data/workspace/{subdir}'


def deerflow_sync_metadata_file(thread_id: str) -> Path:
    return deerflow_thread_workspace_dir(thread_id) / DEERFLOW_SYNC_METADATA


def ensure_deerflow_thread_dirs(thread_id: str) -> None:
    for path in (
        deerflow_thread_workspace_dir(thread_id),
        deerflow_thread_uploads_dir(thread_id),
        deerflow_thread_outputs_dir(thread_id),
    ):
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o777)


def _should_skip_repo_sync_path(rel_path: Path, *, include_git: bool) -> bool:
    rel_str = rel_path.as_posix()
    if rel_str in {'.', ''}:
        return False
    if rel_str == '.deerflow/.env' or rel_str == '.deerflow/vendor' or rel_str.startswith('.deerflow/vendor/'):
        return True
    if rel_str == '.semantic/cache' or rel_str.startswith('.semantic/cache/'):
        return True
    if not include_git and (rel_str == '.git' or rel_str.startswith('.git/')):
        return True
    return any(part in DEERFLOW_SYNC_SKIP_NAMES for part in rel_path.parts)


def _copy_repo_tree(source_root: Path, target_root: Path, *, include_git: bool) -> tuple[int, int]:
    files_copied = 0
    symlinks_copied = 0

    target_root.mkdir(parents=True, exist_ok=True)

    for current_root, dirnames, filenames in os.walk(source_root, topdown=True):
        current_path = Path(current_root)
        rel_root = current_path.relative_to(source_root)
        rel_parts = () if rel_root == Path('.') else rel_root.parts

        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            rel_dir = Path(*rel_parts, dirname)
            if _should_skip_repo_sync_path(rel_dir, include_git=include_git):
                continue
            kept_dirs.append(dirname)
            destination_dir = target_root / rel_dir
            destination_dir.mkdir(parents=True, exist_ok=True)
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            rel_file = Path(*rel_parts, filename)
            if _should_skip_repo_sync_path(rel_file, include_git=include_git):
                continue

            source_path = source_root / rel_file
            target_path = target_root / rel_file
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if source_path.is_symlink():
                if target_path.exists() or target_path.is_symlink():
                    target_path.unlink()
                os.symlink(os.readlink(source_path), target_path)
                symlinks_copied += 1
                continue

            if target_path.is_symlink():
                target_path.unlink()
            shutil.copy2(source_path, target_path)
            files_copied += 1

    return files_copied, symlinks_copied


def _relax_deerflow_workspace_permissions(root: Path) -> None:
    root.chmod(0o777)
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        current_path.chmod(0o777)
        for dirname in dirnames:
            (current_path / dirname).chmod(0o777)
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink():
                continue
            path.chmod(0o666)


def _write_deerflow_sync_metadata(
    thread_id: str,
    repo_root: Path,
    host_workspace: Path,
    workspace_subdir: str,
    include_git: bool,
) -> Path:
    workspace_root = deerflow_thread_workspace_dir(thread_id)
    metadata_path = deerflow_sync_metadata_file(thread_id)
    metadata = {
        'version': 1,
        'thread_id': thread_id,
        'repo_root': str(repo_root),
        'host_workspace': str(host_workspace),
        'sandbox_workspace': deerflow_sandbox_repo_path(workspace_subdir),
        'workspace_root': str(workspace_root),
        'workspace_subdir': _normalize_workspace_subdir(workspace_subdir),
        'include_git': include_git,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    metadata_path.chmod(0o666)
    return metadata_path


def import_repo_to_deerflow_thread(
    thread_id: str,
    repo_root: Path = Path('.'),
    workspace_subdir: str = DEERFLOW_DEFAULT_WORKSPACE_SUBDIR,
    *,
    include_git: bool = True,
) -> DeerFlowRepoSyncReport:
    if not DEERFLOW_VENDOR_DIR.exists():
        raise FileNotFoundError(f'DeerFlow vendor directory missing: {DEERFLOW_VENDOR_DIR}')

    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        raise FileNotFoundError(f'repository root missing: {repo_root}')
    host_workspace = deerflow_repo_workspace_dir(thread_id, workspace_subdir)
    ensure_deerflow_thread_dirs(thread_id)

    if host_workspace.exists():
        shutil.rmtree(host_workspace)

    files_copied, symlinks_copied = _copy_repo_tree(repo_root, host_workspace, include_git=include_git)
    _relax_deerflow_workspace_permissions(host_workspace)
    metadata_path = _write_deerflow_sync_metadata(thread_id, repo_root, host_workspace, workspace_subdir, include_git)
    return DeerFlowRepoSyncReport(
        thread_id=thread_id,
        host_workspace=host_workspace,
        sandbox_workspace=deerflow_sandbox_repo_path(workspace_subdir),
        files_copied=files_copied,
        symlinks_copied=symlinks_copied,
        metadata_file=metadata_path,
    )


def export_repo_from_deerflow_thread(
    thread_id: str,
    repo_root: Path = Path('.'),
    workspace_subdir: str = DEERFLOW_DEFAULT_WORKSPACE_SUBDIR,
) -> DeerFlowRepoSyncReport:
    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        raise FileNotFoundError(f'repository root missing: {repo_root}')
    host_workspace = deerflow_repo_workspace_dir(thread_id, workspace_subdir)
    if not host_workspace.exists():
        raise FileNotFoundError(
            f'DeerFlow workspace missing for thread {thread_id}: {host_workspace}. '
            'Run deerflow-import-repo first.'
        )

    files_copied, symlinks_copied = _copy_repo_tree(host_workspace, repo_root, include_git=False)
    metadata_path = deerflow_sync_metadata_file(thread_id)
    return DeerFlowRepoSyncReport(
        thread_id=thread_id,
        host_workspace=host_workspace,
        sandbox_workspace=deerflow_sandbox_repo_path(workspace_subdir),
        files_copied=files_copied,
        symlinks_copied=symlinks_copied,
        metadata_file=metadata_path if metadata_path.exists() else None,
    )


def sync_deerflow_harness_files() -> list[Path]:
    if not DEERFLOW_VENDOR_DIR.exists():
        return []

    synced: list[Path] = []
    for source, target in (
        (DEERFLOW_CONFIG_FILE, DEERFLOW_VENDOR_CONFIG_FILE),
        (DEERFLOW_RUNTIME_ENV_FILE, DEERFLOW_VENDOR_ENV_FILE),
    ):
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source_text = source.read_text(encoding='utf-8')
        if source == DEERFLOW_RUNTIME_ENV_FILE and DEERFLOW_ENV_FILE.exists():
            source_text = _merge_env_defaults(source_text, DEERFLOW_ENV_FILE.read_text(encoding='utf-8'))
        if not target.exists() or target.read_text(encoding='utf-8') != source_text:
            target.write_text(source_text, encoding='utf-8')
            synced.append(target)

    if DEERFLOW_USER_PROFILE_FILE.exists():
        DEERFLOW_VENDOR_USER_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        source_text = DEERFLOW_USER_PROFILE_FILE.read_text(encoding='utf-8')
        if (
            not DEERFLOW_VENDOR_USER_PROFILE_FILE.exists()
            or DEERFLOW_VENDOR_USER_PROFILE_FILE.read_text(encoding='utf-8') != source_text
        ):
            DEERFLOW_VENDOR_USER_PROFILE_FILE.write_text(source_text, encoding='utf-8')
            synced.append(DEERFLOW_VENDOR_USER_PROFILE_FILE)

    if DEERFLOW_AGENTS_DIR.exists():
        DEERFLOW_VENDOR_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        for agent_dir in sorted(path for path in DEERFLOW_AGENTS_DIR.iterdir() if path.is_dir()):
            target_dir = DEERFLOW_VENDOR_AGENTS_DIR / agent_dir.name
            target_dir.mkdir(parents=True, exist_ok=True)
            for filename in ('config.yaml', 'SOUL.md'):
                source = agent_dir / filename
                if not source.exists():
                    continue
                target = target_dir / filename
                source_text = source.read_text(encoding='utf-8')
                if not target.exists() or target.read_text(encoding='utf-8') != source_text:
                    target.write_text(source_text, encoding='utf-8')
                    synced.append(target)
    return synced


def _parse_markdown_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith('## '):
            current = line[3:].strip().lower()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _clean_section_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _strip_markdown_list_prefix(text: str) -> str:
    stripped = text.strip()
    for prefix in ('- ', '* '):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def collect_epic_specs(epics_dir: Path = EPICS_DIR) -> list[EpicSpec]:
    specs: list[EpicSpec] = []
    for epic_file in sorted(epics_dir.glob('EPIC-*.md')):
        text = epic_file.read_text(encoding='utf-8')
        title_line = text.splitlines()[0].strip()
        title = title_line.removeprefix('# ').strip()
        epic_id = title.split(':', 1)[0].strip()
        sections = _parse_markdown_sections(text)
        goal = ' '.join(_clean_section_lines(sections.get('goal', [])))
        deliverables = [_strip_markdown_list_prefix(line) for line in _clean_section_lines(sections.get('deliverables', []))]
        acceptance = ' '.join(_strip_markdown_list_prefix(line) for line in _clean_section_lines(sections.get('acceptance', [])))
        specs.append(
            EpicSpec(
                epic_id=epic_id,
                title=title,
                source_file=epic_file,
                goal=goal,
                deliverables=deliverables,
                acceptance=acceptance,
            )
        )
    return specs


def _format_epic_objective(spec: EpicSpec) -> str:
    deliverables = '\n'.join(f'- {item}' for item in spec.deliverables)
    live_repo_mount = deerflow_live_repo_mount_path()
    return (
        f'# DeerFlow Objective: {spec.title}\n\n'
        f'Source epic: {spec.source_file.as_posix()}\n\n'
        '## Goal\n'
        f'{spec.goal}\n\n'
        '## Deliverables\n'
        f'{deliverables}\n\n'
        '## Acceptance\n'
        f'- {spec.acceptance}\n\n'
        '## Execution Guardrails\n'
        '- Work only within this repository checkout.\n'
        f'- Prefer the live development directory `{live_repo_mount}` when it is mounted in the sandbox.\n'
        '- When a staged repo mirror exists, use `/mnt/user-data/workspace/repo` as the writable checkout for import/export.\n'
        '- Preserve deterministic semantic outputs under `.semantic/`.\n'
        '- Regenerate semantic artifacts after meaningful changes with `aigit chunk`.\n'
        '- Run `pytest -q` before handing work back.\n'
        '- Update README/docs when user-facing behavior changes.\n'
        '- Do not commit secrets or vendor-state changes unintentionally.\n\n'
        '## Delivery Loop\n'
        '1. Restate the epic objective and identify the smallest reviewable slice.\n'
        '2. Implement the slice with tests first when practical.\n'
        '3. Run validation commands and capture failures precisely.\n'
        '4. Regenerate semantic artifacts and summarize the diff.\n'
        '5. Stop with a review-ready change summary, risks, and next slice.\n'
    )


def build_epic_objective_bundle(
    epics_dir: Path = EPICS_DIR,
    output_dir: Path = DEERFLOW_OBJECTIVES_DIR,
    queue_file: Path = DEERFLOW_QUEUE_FILE,
) -> list[Path]:
    specs = collect_epic_specs(epics_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    queue: list[dict[str, str]] = []
    master_lines = [
        '# DeerFlow Objective Queue: AIGit 10-Epic Roadmap',
        '',
        f'Roadmap: {ROADMAP_FILE.as_posix()}',
        f'Checklist: {TASKS_FILE.as_posix()}',
        '',
        'Execute these objectives in order unless a blocker requires reordering.',
        '',
    ]

    for spec in specs:
        objective_path = output_dir / f'{spec.epic_id}.md'
        objective_path.write_text(_format_epic_objective(spec), encoding='utf-8')
        written.append(objective_path)
        queue.append(
            {
                'id': spec.epic_id,
                'title': spec.title,
                'objective_file': objective_path.as_posix(),
                'source_file': spec.source_file.as_posix(),
            }
        )
        master_lines.append(f'## {spec.epic_id}')
        master_lines.append(f'- Title: {spec.title}')
        master_lines.append(f'- Objective file: {objective_path.as_posix()}')
        master_lines.append(f'- Acceptance: {spec.acceptance}')
        master_lines.append('')

    master_path = output_dir / 'ALL_EPICS.md'
    master_path.write_text('\n'.join(master_lines) + '\n', encoding='utf-8')
    written.append(master_path)
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(json.dumps(queue, indent=2) + '\n', encoding='utf-8')
    return written


def bootstrap_deerflow_files() -> None:
    live_repo_mount = deerflow_live_repo_mount_path()
    _write_file_if_missing(
        DEERFLOW_ENV_FILE,
        '# Copy this file to .deerflow/.env and fill secrets\n'
        'OPENAI_API_KEY=\n'
        'ANTHROPIC_API_KEY=\n'
        'GOOGLE_API_KEY=\n'
        'DEEPSEEK_API_KEY=\n'
        'MOONSHOT_API_KEY=\n'
        'NOVITA_API_KEY=\n'
        'VOLCENGINE_API_KEY=\n'
        'TAVILY_API_KEY=\n'
        'INFOQUEST_API_KEY=\n',
    )
    _write_file_if_missing(
        DEERFLOW_CONFIG_FILE,
        'models:\n'
        '  - name: gpt-4.1\n'
        '    display_name: GPT-4.1\n'
        '    description: Default OpenAI coding model for the AIGit DeerFlow harness.\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: gpt-4.1\n'
        '    api_key: $OPENAI_API_KEY\n'
        '    max_tokens: 8192\n'
        '    temperature: 0.2\n'
        '\n'
        '  - name: gpt-4o\n'
        '    display_name: GPT-4o\n'
        '    description: Balanced multimodal model for operator-facing DeerFlow tasks.\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: gpt-4o\n'
        '    api_key: $OPENAI_API_KEY\n'
        '    max_tokens: 8192\n'
        '    temperature: 0.2\n'
        '\n'
        '  - name: gpt-4o-mini\n'
        '    display_name: GPT-4o Mini\n'
        '    description: Fast low-cost model for lightweight DeerFlow loops.\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: gpt-4o-mini\n'
        '    api_key: $OPENAI_API_KEY\n'
        '    max_tokens: 4096\n'
        '    temperature: 0.2\n'
        '\n'
        '  - name: gpt-4.1-mini\n'
        '    display_name: GPT-4.1 Mini\n'
        '    description: Fast OpenAI fallback for code review and status updates.\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: gpt-4.1-mini\n'
        '    api_key: $OPENAI_API_KEY\n'
        '    max_tokens: 4096\n'
        '    temperature: 0.2\n'
        '\n'
        '  - name: gpt-4.1-nano\n'
        '    display_name: GPT-4.1 Nano\n'
        '    description: Cheapest OpenAI model for titles, summaries, and quick planning.\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: gpt-4.1-nano\n'
        '    api_key: $OPENAI_API_KEY\n'
        '    max_tokens: 2048\n'
        '    temperature: 0.2\n'
        '\n'
        '  - name: claude-sonnet-4\n'
        '    display_name: Claude Sonnet 4\n'
        '    description: Frontier review model for release-critical AIGit changes.\n'
        '    use: langchain_anthropic:ChatAnthropic\n'
        '    model: claude-sonnet-4-20250514\n'
        '    api_key: $ANTHROPIC_API_KEY\n'
        '    max_tokens: 8192\n'
        '    supports_vision: true\n'
        '    supports_thinking: true\n'
        '    when_thinking_enabled:\n'
        '      thinking:\n'
        '        type: enabled\n'
        '\n'
        '  - name: gemini-2.5-pro\n'
        '    display_name: Gemini 2.5 Pro\n'
        '    description: Long-context synthesis model for roadmap and repo-wide reasoning.\n'
        '    use: langchain_google_genai:ChatGoogleGenerativeAI\n'
        '    model: gemini-2.5-pro\n'
        '    google_api_key: $GOOGLE_API_KEY\n'
        '    max_tokens: 8192\n'
        '    supports_vision: true\n'
        '\n'
        '  - name: deepseek-reasoner\n'
        '    display_name: DeepSeek Reasoner\n'
        '    description: Native DeepSeek reasoning model for semantic diff and merge analysis.\n'
        '    use: deerflow.models.patched_deepseek:PatchedChatDeepSeek\n'
        '    model: deepseek-reasoner\n'
        '    api_key: $DEEPSEEK_API_KEY\n'
        '    max_tokens: 16384\n'
        '    supports_thinking: true\n'
        '    when_thinking_enabled:\n'
        '      extra_body:\n'
        '        thinking:\n'
        '          type: enabled\n'
        '\n'
        '  - name: kimi-k2.5\n'
        '    display_name: Kimi K2.5\n'
        '    description: Moonshot large-context model for multi-epic planning and synthesis.\n'
        '    use: deerflow.models.patched_deepseek:PatchedChatDeepSeek\n'
        '    model: kimi-k2.5\n'
        '    api_base: https://api.moonshot.cn/v1\n'
        '    api_key: $MOONSHOT_API_KEY\n'
        '    max_tokens: 32768\n'
        '    supports_thinking: true\n'
        '    supports_vision: true\n'
        '    when_thinking_enabled:\n'
        '      extra_body:\n'
        '        thinking:\n'
        '          type: enabled\n'
        '\n'
        '  - name: deepseek-v3.2\n'
        '    display_name: DeepSeek V3.2\n'
        '    description: OpenAI-compatible DeepSeek V3.2 access through Novita for coding-heavy flows.\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: deepseek/deepseek-v3.2\n'
        '    api_key: $NOVITA_API_KEY\n'
        '    base_url: https://api.novita.ai/openai\n'
        '    max_tokens: 8192\n'
        '    temperature: 0.1\n'
        '    supports_thinking: true\n'
        '    when_thinking_enabled:\n'
        '      extra_body:\n'
        '        thinking:\n'
        '          type: enabled\n'
        '\n'
        'tool_groups:\n'
        '  - name: file:read\n'
        '  - name: file:write\n'
        '  - name: bash\n'
        '\n'
        'tools:\n'
        '  - name: ls\n'
        '    group: file:read\n'
        '    use: deerflow.sandbox.tools:ls_tool\n'
        '\n'
        '  - name: read_file\n'
        '    group: file:read\n'
        '    use: deerflow.sandbox.tools:read_file_tool\n'
        '\n'
        '  - name: write_file\n'
        '    group: file:write\n'
        '    use: deerflow.sandbox.tools:write_file_tool\n'
        '\n'
        '  - name: str_replace\n'
        '    group: file:write\n'
        '    use: deerflow.sandbox.tools:str_replace_tool\n'
        '\n'
        '  - name: bash\n'
        '    group: bash\n'
        '    use: deerflow.sandbox.tools:bash_tool\n'
        '\n'
        'sandbox:\n'
        '  use: deerflow.community.aio_sandbox:AioSandboxProvider\n'
        '  workspace_repo_subdir: repo\n'
        '  mounts:\n'
        f'    - host_path: {json.dumps(live_repo_mount)}\n'
        f'      container_path: {json.dumps(live_repo_mount)}\n'
        '      read_only: false\n'
        '\n'
        'skills:\n'
        f'  path: {json.dumps(str((Path(live_repo_mount) / "skills" / "custom").resolve()))}\n'
        '  container_path: /mnt/skills\n'
        '\n'
        'subagents:\n'
        '  timeout_seconds: 1800\n'
        '  agents:\n'
        '    general-purpose:\n'
        '      timeout_seconds: 2400\n'
        '    bash:\n'
        '      timeout_seconds: 600\n'
        '\n'
        'channels:\n'
        '  session:\n'
        '    assistant_id: aigit-orchestrator\n'
        '    config:\n'
        '      recursion_limit: 120\n'
        '    context:\n'
        '      thinking_enabled: true\n'
        '      is_plan_mode: true\n'
        '      subagent_enabled: true\n',
    )
    _write_file_if_missing(
        DEERFLOW_USER_PROFILE_FILE,
        '# AIGit Operator Profile\n\n'
        '- This DeerFlow deployment exists to work on AIGit repositories.\n'
        '- Preserve Git-native behavior and deterministic semantic artifacts under `.semantic/`.\n'
        '- Prefer focused, reviewable changes and keep docs/tests aligned with behavior.\n'
        '- Treat `.deerflow/.env` and vendored runtime files as sensitive operational state.\n',
    )
    _write_deerflow_agent_if_missing(
        'aigit-orchestrator',
        'name: aigit-orchestrator\n'
        'description: Default AIGit DeerFlow agent for repo-aware implementation, testing, and semantic artifact upkeep.\n'
        'tool_groups:\n'
        '  - file:read\n'
        '  - file:write\n'
        '  - bash\n',
        '# AIGit Orchestrator\n\n'
        'You are the default DeerFlow operator for AIGit.\n\n'
        '## Mission\n'
        '- Ship changes inside the current AIGit repository with tests, semantic artifacts, and docs kept in sync.\n'
        '- Use the custom AIGit skill bundle under `skills/custom/deerflow-aigit-autopilot/` when it shortens setup or execution.\n\n'
        '## Guardrails\n'
        '- Prefer the live checkout at `/workspaces/aigit` when available.\n'
        '- When working inside a staged DeerFlow thread workspace, treat `/mnt/user-data/workspace/repo` as the writable checkout.\n'
        '- Re-run `pytest -q` and `python -m aigit.cli chunk --repo .` after meaningful changes.\n'
        '- Keep release notes, README, and operator docs aligned with actual shipped behavior.\n',
    )
    _write_deerflow_agent_if_missing(
        'aigit-semantic-maintainer',
        'name: aigit-semantic-maintainer\n'
        'description: Focused AIGit agent for chunk graph integrity, provenance, semantic diff, and semantic merge workflows.\n'
        'model: deepseek-reasoner\n'
        'tool_groups:\n'
        '  - file:read\n'
        '  - file:write\n'
        '  - bash\n',
        '# AIGit Semantic Maintainer\n\n'
        'You specialize in AIGit semantic storage correctness.\n\n'
        '## Focus\n'
        '- Deterministic chunk generation, lineage continuity, semantic diff quality, semantic merge analysis, and provenance verification.\n'
        '- Changes under `.semantic/`, parser behavior, chunk identity, and CI freshness enforcement.\n\n'
        '## Output Contract\n'
        '- Explain any semantic artifact changes in terms of chunk identity, hashes, and lineage effects.\n'
        '- Call out risks to determinism or false-positive semantic diffs before finalizing work.\n',
    )
    _write_deerflow_agent_if_missing(
        'aigit-release-governor',
        'name: aigit-release-governor\n'
        'description: AIGit release agent for roadmap alignment, CI gating, docs consistency, and operator handoff quality.\n'
        'model: claude-sonnet-4\n'
        'tool_groups:\n'
        '  - file:read\n'
        '  - file:write\n'
        '  - bash\n',
        '# AIGit Release Governor\n\n'
        'You are responsible for release readiness across code, CI, docs, and DeerFlow operations.\n\n'
        '## Responsibilities\n'
        '- Keep roadmap status, README claims, and shipped implementation aligned.\n'
        '- Preserve non-destructive CI behavior and ensure maintenance automation only changes intended files.\n'
        '- Produce concise release notes, operator steps, and risk summaries.\n',
    )
    _write_file_if_missing(
        DEERFLOW_LAUNCH_SCRIPT,
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        'DEERFLOW_DIR="$REPO_ROOT/.deerflow/vendor/deer-flow"\n'
        'LOCAL_CONFIG="$REPO_ROOT/.deerflow/config.yaml"\n'
        'LOCAL_ENV="$REPO_ROOT/.deerflow/.env"\n'
        'LOCAL_ENV_EXAMPLE="$REPO_ROOT/.deerflow/.env.example"\n'
        'LOCAL_AGENTS_DIR="$REPO_ROOT/.deerflow/agents"\n'
        'LOCAL_USER_PROFILE="$REPO_ROOT/.deerflow/USER.md"\n'
        'RUNTIME_HOME="$DEERFLOW_DIR/backend/.deer-flow"\n'
        'if [ ! -d "$DEERFLOW_DIR" ]; then\n'
        '  echo "deer-flow vendor directory missing. Run: aigit init-deerflow" >&2\n'
        '  exit 1\n'
        'fi\n'
        'if [ -f "$LOCAL_CONFIG" ]; then\n'
        '  cp "$LOCAL_CONFIG" "$DEERFLOW_DIR/config.yaml"\n'
        'fi\n'
        'if [ -f "$LOCAL_ENV" ]; then\n'
        '  cp "$LOCAL_ENV" "$DEERFLOW_DIR/.env"\n'
        'elif [ -f "$LOCAL_ENV_EXAMPLE" ] && [ ! -f "$DEERFLOW_DIR/.env" ]; then\n'
        '  cp "$LOCAL_ENV_EXAMPLE" "$DEERFLOW_DIR/.env"\n'
        'fi\n'
        'mkdir -p "$RUNTIME_HOME/agents"\n'
        'if [ -f "$LOCAL_USER_PROFILE" ]; then\n'
        '  cp "$LOCAL_USER_PROFILE" "$RUNTIME_HOME/USER.md"\n'
        'fi\n'
        'if [ -d "$LOCAL_AGENTS_DIR" ]; then\n'
        '  for agent_dir in "$LOCAL_AGENTS_DIR"/*; do\n'
        '    [ -d "$agent_dir" ] || continue\n'
        '    target_dir="$RUNTIME_HOME/agents/$(basename "$agent_dir")"\n'
        '    mkdir -p "$target_dir"\n'
        '    [ -f "$agent_dir/config.yaml" ] && cp "$agent_dir/config.yaml" "$target_dir/config.yaml"\n'
        '    [ -f "$agent_dir/SOUL.md" ] && cp "$agent_dir/SOUL.md" "$target_dir/SOUL.md"\n'
        '  done\n'
        'fi\n'
        'export DEER_FLOW_ROOT="$DEERFLOW_DIR"\n'
        'cd "$DEERFLOW_DIR"\n'
        'make docker-init\n'
        'make docker-start\n'
        'docker restart deer-flow-nginx >/dev/null 2>&1 || true\n',
    )
    _write_file_if_missing(
        DEERFLOW_EPIC_LAUNCH_SCRIPT,
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        'QUEUE_FILE="$REPO_ROOT/.deerflow/epic_queue.json"\n'
        'OBJECTIVES_DIR="$REPO_ROOT/.deerflow/objectives"\n'
        '"$REPO_ROOT/scripts/run_deerflow.sh"\n'
        'if [ ! -f "$QUEUE_FILE" ]; then\n'
        '  echo "epic queue missing. Run: aigit launch-epics" >&2\n'
        '  exit 1\n'
        'fi\n'
        'echo "DeerFlow harness is running for the roadmap."\n'
        'echo "Workspace UI: http://localhost:2026/workspace/chats/new"\n'
        'echo "Root URL http://localhost:2026 is the generic DeerFlow landing page."\n'
        'echo "Load the master objective: $OBJECTIVES_DIR/ALL_EPICS.md"\n'
        'echo "Per-epic objective files are in: $OBJECTIVES_DIR"\n'
        'echo "Queue manifest: $QUEUE_FILE"\n'
        'echo "Direct AIO sandbox contract: /mnt/user-data is the mounted thread root."\n'
        f'echo "Live development directory mount: {live_repo_mount}"\n'
        'echo "Stage the repo into a thread with: aigit deerflow-import-repo --thread-id <thread-id>"\n'
        f'echo "Prefer DeerFlow work in: {live_repo_mount}"\n'
        'echo "Tell DeerFlow to work in: /mnt/user-data/workspace/repo"\n'
        'echo "Pull changes back with: aigit deerflow-export-repo --thread-id <thread-id>"\n'
        'echo "If the harness loses context or returns sandbox-path nonsense, run: $REPO_ROOT/scripts/recover_deerflow.sh"\n',
    )
    _write_file_if_missing(
        DEERFLOW_RECOVERY_SCRIPT,
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        'DEERFLOW_DIR="$REPO_ROOT/.deerflow/vendor/deer-flow"\n'
        'LOCAL_CONFIG="$REPO_ROOT/.deerflow/config.yaml"\n'
        'LOCAL_ENV="$REPO_ROOT/.deerflow/.env"\n'
        'LOCAL_ENV_EXAMPLE="$REPO_ROOT/.deerflow/.env.example"\n'
        'LOCAL_AGENTS_DIR="$REPO_ROOT/.deerflow/agents"\n'
        'LOCAL_USER_PROFILE="$REPO_ROOT/.deerflow/USER.md"\n'
        'RUNTIME_HOME="$DEERFLOW_DIR/backend/.deer-flow"\n'
        'if [ ! -d "$DEERFLOW_DIR" ]; then\n'
        '  echo "deer-flow vendor directory missing. Run: aigit init-deerflow" >&2\n'
        '  exit 1\n'
        'fi\n'
        'if [ -f "$LOCAL_CONFIG" ]; then\n'
        '  cp "$LOCAL_CONFIG" "$DEERFLOW_DIR/config.yaml"\n'
        'fi\n'
        'if [ -f "$LOCAL_ENV" ]; then\n'
        '  cp "$LOCAL_ENV" "$DEERFLOW_DIR/.env"\n'
        'elif [ -f "$LOCAL_ENV_EXAMPLE" ] && [ ! -f "$DEERFLOW_DIR/.env" ]; then\n'
        '  cp "$LOCAL_ENV_EXAMPLE" "$DEERFLOW_DIR/.env"\n'
        'fi\n'
        'mkdir -p "$RUNTIME_HOME/agents"\n'
        'if [ -f "$LOCAL_USER_PROFILE" ]; then\n'
        '  cp "$LOCAL_USER_PROFILE" "$RUNTIME_HOME/USER.md"\n'
        'fi\n'
        'if [ -d "$LOCAL_AGENTS_DIR" ]; then\n'
        '  for agent_dir in "$LOCAL_AGENTS_DIR"/*; do\n'
        '    [ -d "$agent_dir" ] || continue\n'
        '    target_dir="$RUNTIME_HOME/agents/$(basename "$agent_dir")"\n'
        '    mkdir -p "$target_dir"\n'
        '    [ -f "$agent_dir/config.yaml" ] && cp "$agent_dir/config.yaml" "$target_dir/config.yaml"\n'
        '    [ -f "$agent_dir/SOUL.md" ] && cp "$agent_dir/SOUL.md" "$target_dir/SOUL.md"\n'
        '  done\n'
        'fi\n'
        'export DEER_FLOW_ROOT="$DEERFLOW_DIR"\n'
        'cd "$DEERFLOW_DIR"\n'
        'make docker-stop || true\n'
        'make docker-start\n'
        'docker restart deer-flow-nginx >/dev/null 2>&1 || true\n'
        'for endpoint in "http://localhost:2026/api/models" "http://localhost:2026/api/langgraph/openapi.json"; do\n'
        '  ready=0\n'
        '  for _ in $(seq 1 20); do\n'
        '    if curl -fsS "$endpoint" >/dev/null 2>&1; then\n'
        '      ready=1\n'
        '      break\n'
        '    fi\n'
        '    sleep 2\n'
        '  done\n'
        '  if [ "$ready" -ne 1 ]; then\n'
        '    echo "DeerFlow recovered but did not pass health check: $endpoint" >&2\n'
        '    exit 1\n'
        '  fi\n'
        'done\n'
        'echo "DeerFlow recovery complete."\n'
        'echo "Workspace UI: http://localhost:2026/workspace/chats/new"\n'
        f'echo "Live development directory mount: {live_repo_mount}"\n'
        'echo "Reload the master objective: $REPO_ROOT/.deerflow/objectives/ALL_EPICS.md"\n',
    )
    DEERFLOW_LAUNCH_SCRIPT.chmod(0o755)
    DEERFLOW_EPIC_LAUNCH_SCRIPT.chmod(0o755)
    DEERFLOW_RECOVERY_SCRIPT.chmod(0o755)


def cmd_init_deerflow(args: argparse.Namespace) -> int:
    bootstrap_deerflow_files()
    if args.skip_clone:
        print('initialized local deerflow config files (skip clone)')
        return 0

    DEERFLOW_VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not DEERFLOW_VENDOR_DIR.exists():
        subprocess.run(
            [
                'git',
                'clone',
                '--depth',
                '1',
                args.repo,
                str(DEERFLOW_VENDOR_DIR),
            ],
            check=True,
        )
    else:
        vendor_status = subprocess.run(
            ['git', '-C', str(DEERFLOW_VENDOR_DIR), 'status', '--porcelain'],
            check=True,
            text=True,
            capture_output=True,
        )
        if vendor_status.stdout.strip():
            print('vendored deer-flow checkout has local modifications; skipping upstream pull to avoid overwriting them')
        else:
            subprocess.run(['git', '-C', str(DEERFLOW_VENDOR_DIR), 'pull', '--ff-only'], check=True)

    vendor_config_exists = any(
        (DEERFLOW_VENDOR_DIR / name).exists() for name in ('config.yaml', 'config.yml', 'configure.yml')
    )
    if not vendor_config_exists:
        subprocess.run(['make', 'config'], cwd=DEERFLOW_VENDOR_DIR, check=True)
    synced_files = sync_deerflow_harness_files()
    if synced_files:
        print('synced DeerFlow runtime files into the vendored harness:')
        for path in synced_files:
            print(f'  - {path}')
    print(f'initialized deer-flow harness in {DEERFLOW_VENDOR_DIR}')
    print('next: copy .deerflow/.env.example to .deerflow/.env and set API keys')
    return 0


def cmd_launch_epics(args: argparse.Namespace) -> int:
    bootstrap_deerflow_files()
    written = build_epic_objective_bundle(Path(args.epics_dir), Path(args.output_dir), Path(args.queue_file))

    if args.bootstrap_deerflow:
        init_args = argparse.Namespace(repo=args.repo, skip_clone=args.skip_clone)
        init_code = cmd_init_deerflow(init_args)
        if init_code != 0:
            return init_code

    print(f'prepared {len(written)} DeerFlow objective files')
    print(f'master objective: {(Path(args.output_dir) / "ALL_EPICS.md").as_posix()}')

    if not args.start_harness:
        return 0

    if not DEERFLOW_VENDOR_DIR.exists():
        print('deer-flow vendor directory missing; rerun with --bootstrap-deerflow or run aigit init-deerflow')
        return 1
    if ensure_deerflow_runtime_env():
        print('seeded .deerflow/.env from .deerflow/.env.example')
    synced_files = sync_deerflow_harness_files()
    if synced_files:
        print('synced DeerFlow runtime files into the vendored harness:')
        for path in synced_files:
            print(f'  - {path}')

    missing_keys = missing_deerflow_env_keys()
    if missing_keys:
        print(f'missing required DeerFlow env keys: {", ".join(missing_keys)}')
        return 2

    subprocess.run([str(DEERFLOW_EPIC_LAUNCH_SCRIPT.resolve())], check=True)
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    repo_root = Path('.').resolve()
    bootstrap_deerflow_files()

    if args.bootstrap_deerflow or not DEERFLOW_VENDOR_DIR.exists():
        init_args = argparse.Namespace(repo=args.deerflow_repo, skip_clone=args.skip_clone)
        init_code = cmd_init_deerflow(init_args)
        if init_code != 0:
            return init_code

    if not DEERFLOW_VENDOR_DIR.exists():
        print('deer-flow vendor directory missing; run `aigit init-deerflow` or rerun `aigit up --bootstrap-deerflow`')
        return 1

    if ensure_deerflow_runtime_env():
        print('seeded or refreshed .deerflow/.env from .deerflow/.env.example')

    synced_files = sync_deerflow_harness_files()
    if synced_files:
        print('synced DeerFlow runtime files into the vendored harness:')
        for path in synced_files:
            print(f'  - {path}')

    missing_keys = missing_deerflow_env_keys()
    if missing_keys:
        print(f'warning: missing DeerFlow env keys: {", ".join(missing_keys)}')
        print('the local stack can still boot, but model-backed calls may fail until those keys are set')

    subprocess.run([str(DEERFLOW_RECOVERY_SCRIPT.resolve())], check=True)

    if not args.skip_serve_api:
        ok, message = _ensure_background_service(
            'serve-api',
            repo_root,
            f'http://{args.api_host}:{args.api_port}/healthz',
            ['serve-api', '--host', args.api_host, '--port', str(args.api_port)],
            startup_timeout=10,
        )
        print(message)
        if not ok:
            return 1

    if not args.skip_admin_ui:
        ok, message = _ensure_background_service(
            'admin-ui',
            repo_root,
            f'http://{args.admin_host}:{args.admin_port}',
            ['admin-ui', '--repo', str(repo_root), '--host', args.admin_host, '--port', str(args.admin_port)],
            startup_timeout=30,
        )
        print(message)
        if not ok:
            return 1

    print('AIGit stack is up:')
    print('  - DeerFlow UI: http://localhost:2026/workspace/chats/new')
    if not args.skip_serve_api:
        print(f'  - Chunk API: http://{args.api_host}:{args.api_port}/healthz')
    if not args.skip_admin_ui:
        print(f'  - Admin UI: http://{args.admin_host}:{args.admin_port}')
    return 0


def cmd_deerflow_workspace_path(args: argparse.Namespace) -> int:
    try:
        host_workspace = deerflow_repo_workspace_dir(args.thread_id, args.workspace_subdir)
        sandbox_workspace = deerflow_sandbox_repo_path(args.workspace_subdir)
    except ValueError as exc:
        print(str(exc))
        return 2

    print(f'host workspace: {host_workspace}')
    print(f'sandbox workspace: {sandbox_workspace}')
    return 0


def cmd_deerflow_import_repo(args: argparse.Namespace) -> int:
    try:
        report = import_repo_to_deerflow_thread(
            thread_id=args.thread_id,
            repo_root=Path(args.repo),
            workspace_subdir=args.workspace_subdir,
            include_git=not args.exclude_git,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1

    print(f'staged {report.files_copied} files and {report.symlinks_copied} symlinks for thread {report.thread_id}')
    print(f'host workspace: {report.host_workspace}')
    print(f'sandbox workspace: {report.sandbox_workspace}')
    if report.metadata_file is not None:
        print(f'metadata: {report.metadata_file}')
    print('tell DeerFlow to work inside that sandbox path and keep changes there until export')
    return 0


def cmd_deerflow_export_repo(args: argparse.Namespace) -> int:
    try:
        report = export_repo_from_deerflow_thread(
            thread_id=args.thread_id,
            repo_root=Path(args.repo),
            workspace_subdir=args.workspace_subdir,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1

    print(f'exported {report.files_copied} files and {report.symlinks_copied} symlinks from thread {report.thread_id}')
    print(f'source workspace: {report.host_workspace}')
    print('git metadata is intentionally not imported back; apply deletions manually if the sandbox removed files')
    return 0


def _read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _count_files_in_tree(root: Path) -> int:
    if not root.exists():
        return 0
    count = 0
    for current_root, _, filenames in os.walk(root):
        current_path = Path(current_root)
        for filename in filenames:
            path = current_path / filename
            if path.is_file() and not path.is_symlink():
                count += 1
    return count


def _latest_mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    latest = path.stat().st_mtime
    if path.is_dir():
        for current_root, dirnames, filenames in os.walk(path):
            current_path = Path(current_root)
            latest = max(latest, current_path.stat().st_mtime)
            for dirname in dirnames:
                latest = max(latest, (current_path / dirname).stat().st_mtime)
            for filename in filenames:
                latest = max(latest, (current_path / filename).stat().st_mtime)
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _run_command_capture(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_status_summary(repo_root: Path = Path('.')) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if not (repo_root / '.git').exists():
        return {
            'available': False,
            'branch': None,
            'dirty': False,
            'changed_count': 0,
            'changed_files': [],
        }

    branch_code, branch_stdout, branch_stderr = _run_command_capture(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_root)
    status_code, status_stdout, status_stderr = _run_command_capture(['git', 'status', '--short'], cwd=repo_root)
    changed_files = [line for line in status_stdout.splitlines() if line.strip()] if status_code == 0 else []
    return {
        'available': branch_code == 0 and status_code == 0,
        'branch': branch_stdout if branch_code == 0 else None,
        'dirty': bool(changed_files),
        'changed_count': len(changed_files),
        'changed_files': changed_files[:50],
        'error': branch_stderr or status_stderr or None,
    }


def deerflow_api_health() -> list[dict[str, Any]]:
    checks: list[tuple[str, str]] = [
        ('models', 'http://127.0.0.1:2026/api/models'),
        ('openapi', 'http://127.0.0.1:2026/api/langgraph/openapi.json'),
    ]
    results: list[dict[str, Any]] = []
    for name, url in checks:
        try:
            with urllib_request.urlopen(url, timeout=2.5) as response:
                body = response.read(256)
                results.append(
                    {
                        'name': name,
                        'url': url,
                        'ok': 200 <= response.status < 300,
                        'status': response.status,
                        'detail': body.decode('utf-8', errors='replace')[:120],
                    }
                )
        except urllib_error.URLError as exc:
            results.append({'name': name, 'url': url, 'ok': False, 'status': None, 'detail': str(exc.reason)})
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            results.append({'name': name, 'url': url, 'ok': False, 'status': None, 'detail': str(exc)})
    return results


def list_deerflow_containers() -> list[dict[str, Any]]:
    if shutil.which('docker') is None:
        return []
    code, stdout, _ = _run_command_capture(['docker', 'ps', '-a', '--format', '{{json .}}'])
    if code != 0:
        return []

    containers: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(row.get('Names', ''))
        image = str(row.get('Image', ''))
        ports = str(row.get('Ports', ''))
        haystack = ' '.join([name.lower(), image.lower(), ports.lower()])
        if 'deer' not in haystack and '2026' not in haystack:
            continue
        containers.append(
            {
                'name': name,
                'image': image,
                'status': row.get('Status', ''),
                'state': row.get('State', ''),
                'ports': ports,
            }
        )
    return containers


def get_deerflow_container_logs(container_name: str, tail_lines: int = 200) -> str:
    container = container_name.strip()
    if not container:
        return 'enter a container name to inspect logs'
    if shutil.which('docker') is None:
        return 'docker is not available in this environment'
    code, stdout, stderr = _run_command_capture(['docker', 'logs', '--tail', str(max(tail_lines, 1)), container])
    if code != 0:
        return stderr or stdout or f'failed to read logs for {container}'
    return stdout or f'no log output for {container}'


def collect_semantic_summary(repo_root: Path = Path('.')) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = _repo_semantic_path(repo_root, MANIFEST_FILE)
    edges_path = _repo_semantic_path(repo_root, EDGES_FILE)
    provenance_path = _repo_semantic_path(repo_root, SEMANTIC_DIR / 'provenance.jsonl')
    schema_path = _repo_semantic_path(repo_root, SCHEMA_FILE)
    ruleset_path = _repo_semantic_path(repo_root, RULESET_FILE)

    chunks = _read_jsonl_rows(manifest_path)
    chunk_types: dict[str, int] = {}
    for chunk in chunks:
        chunk_type = str(chunk.get('chunk_type', 'unknown'))
        chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1

    return {
        'manifest_exists': manifest_path.exists(),
        'manifest_path': str(manifest_path),
        'last_updated': _latest_mtime_iso(manifest_path),
        'chunk_count': len(chunks),
        'edge_count': len(_read_jsonl_rows(edges_path)),
        'provenance_count': len(_read_jsonl_rows(provenance_path)),
        'schema_version': schema_path.read_text(encoding='utf-8').strip() if schema_path.exists() else None,
        'ruleset_present': ruleset_path.exists(),
        'chunk_types': [
            {'chunk_type': chunk_type, 'count': count}
            for chunk_type, count in sorted(chunk_types.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def collect_epic_queue_status(repo_root: Path = Path('.')) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    queue_path = repo_root / DEERFLOW_QUEUE_FILE
    master_path = repo_root / DEERFLOW_OBJECTIVES_DIR / 'ALL_EPICS.md'
    entries = _read_json_file(queue_path)
    if not isinstance(entries, list):
        entries = []

    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        objective_file = repo_root / str(entry.get('objective_file', ''))
        source_file = repo_root / str(entry.get('source_file', ''))
        normalized_entries.append(
            {
                'id': entry.get('id', ''),
                'title': entry.get('title', ''),
                'objective_file': entry.get('objective_file', ''),
                'objective_exists': objective_file.exists(),
                'source_file': entry.get('source_file', ''),
                'source_exists': source_file.exists(),
            }
        )

    return {
        'queue_exists': queue_path.exists(),
        'queue_path': str(queue_path),
        'master_exists': master_path.exists(),
        'master_path': str(master_path),
        'objective_count': len(normalized_entries),
        'entries': normalized_entries,
    }


def list_deerflow_threads() -> list[dict[str, Any]]:
    threads_root = deerflow_threads_dir()
    if not threads_root.exists():
        return []

    summaries: list[dict[str, Any]] = []
    for thread_dir in sorted((path for path in threads_root.iterdir() if path.is_dir()), key=lambda item: item.name):
        thread_id = thread_dir.name
        workspace_root = deerflow_thread_workspace_dir(thread_id)
        uploads_root = deerflow_thread_uploads_dir(thread_id)
        outputs_root = deerflow_thread_outputs_dir(thread_id)
        metadata_path = deerflow_sync_metadata_file(thread_id)
        metadata = _read_json_file(metadata_path)
        workspace_subdir = DEERFLOW_DEFAULT_WORKSPACE_SUBDIR
        if isinstance(metadata, dict):
            workspace_subdir = str(metadata.get('workspace_subdir') or DEERFLOW_DEFAULT_WORKSPACE_SUBDIR)
        repo_workspace = deerflow_repo_workspace_dir(thread_id, workspace_subdir)
        summaries.append(
            {
                'thread_id': thread_id,
                'thread_path': str(thread_dir),
                'workspace_path': str(workspace_root),
                'repo_workspace_path': str(repo_workspace),
                'sandbox_workspace': str(metadata.get('sandbox_workspace')) if isinstance(metadata, dict) else deerflow_sandbox_repo_path(workspace_subdir),
                'workspace_files': _count_files_in_tree(workspace_root),
                'repo_workspace_files': _count_files_in_tree(repo_workspace),
                'upload_files': _count_files_in_tree(uploads_root),
                'output_files': _count_files_in_tree(outputs_root),
                'metadata_present': metadata_path.exists(),
                'metadata_path': str(metadata_path),
                'last_updated': _latest_mtime_iso(thread_dir),
                'metadata': metadata if isinstance(metadata, dict) else {},
            }
        )

    return sorted(summaries, key=lambda item: item.get('last_updated') or '', reverse=True)


def get_deerflow_thread_details(thread_id: str) -> dict[str, Any] | None:
    normalized = thread_id.strip()
    if not normalized:
        return None
    for thread in list_deerflow_threads():
        if thread['thread_id'] == normalized:
            return thread
    return None


def collect_admin_snapshot(repo_root: Path = Path('.')) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    env_values = _parse_env_file(repo_root / DEERFLOW_RUNTIME_ENV_FILE)
    configured_keys = {
        key: bool(env_values.get(key))
        for key in (
            'OPENAI_API_KEY',
            'ANTHROPIC_API_KEY',
            'GOOGLE_API_KEY',
            'DEEPSEEK_API_KEY',
            'MOONSHOT_API_KEY',
            'NOVITA_API_KEY',
            'VOLCENGINE_API_KEY',
            'TAVILY_API_KEY',
            'INFOQUEST_API_KEY',
        )
    }
    queue = collect_epic_queue_status(repo_root)
    threads = list_deerflow_threads()
    containers = list_deerflow_containers()

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'repo_root': str(repo_root),
        'git': git_status_summary(repo_root),
        'semantic': collect_semantic_summary(repo_root),
        'epics': queue,
        'threads': threads,
        'deerflow': {
            'vendor_exists': (repo_root / DEERFLOW_VENDOR_DIR).exists(),
            'config_present': (repo_root / DEERFLOW_CONFIG_FILE).exists(),
            'runtime_env_present': (repo_root / DEERFLOW_RUNTIME_ENV_FILE).exists(),
            'launch_script_present': (repo_root / DEERFLOW_LAUNCH_SCRIPT).exists(),
            'recovery_script_present': (repo_root / DEERFLOW_RECOVERY_SCRIPT).exists(),
            'objective_count': queue['objective_count'],
            'thread_count': len(threads),
            'configured_keys': configured_keys,
            'api_health': deerflow_api_health(),
            'containers': containers,
        },
    }


def cmd_admin_ui(args: argparse.Namespace) -> int:
    try:
        from aigit.admin_ui import launch_admin_ui
    except ImportError as exc:
        print(f'failed to import Gradio admin UI dependencies: {exc}')
        print('install project dependencies with `python -m pip install -e .` and retry')
        return 1

    launch_admin_ui(repo_root=Path(args.repo).resolve(), host=args.host, port=args.port, share=args.share)
    return 0


def serve_api(args: argparse.Namespace) -> int:
    manifest_file = _repo_semantic_path(Path('.').resolve(), MANIFEST_FILE)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == '/healthz':
                self._send(200, {'status': 'ok'})
                return
            if self.path.startswith('/chunks'):
                if not manifest_file.exists():
                    self._send(404, {'error': 'manifest missing'})
                    return
                chunks = [json.loads(line) for line in manifest_file.read_text(encoding='utf-8').splitlines() if line]
                self._send(200, {'chunks': chunks})
                return
            self._send(404, {'error': 'not found'})

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'serving API on http://{args.host}:{args.port}')
    server.serve_forever()


def cmd_improve(args: argparse.Namespace) -> int:
    """Lightweight auto improvement loop that works within Codespaces constraints.

    The loop does not require Docker or DeerFlow.  It runs the local validation
    cycle (tests + semantic rebuild) and reports a concise status summary so
    operators can see at a glance whether the working tree is healthy.

    Steps
    -----
    1. Rebuild semantic artifacts (``aigit chunk``).
    2. Run the test suite with ``pytest``.
    3. Print a short status summary.
    """
    repo_root = Path(args.repo).resolve()
    print('=== AIGit improve loop (Codespaces-safe) ===')

    # Step 1: rebuild semantic artifacts
    print('\n[1/2] Rebuilding semantic artifacts...')
    chunk_args = argparse.Namespace(repo=str(repo_root))
    chunk_rc = cmd_chunk(chunk_args)
    if chunk_rc != 0:
        print('ERROR: semantic artifact rebuild failed')
        return chunk_rc
    print('      semantic artifacts up to date')

    # Step 2: run tests
    print('\n[2/2] Running test suite...')
    if importlib.util.find_spec('pytest') is None:
        print('\nIMPROVE LOOP: pytest is not installed in the active Python environment')
        print('install development dependencies with `python -m pip install -e ".[dev]"` and rerun `aigit improve`')
        return 2
    pytest_cmd = [sys.executable, '-m', 'pytest', '--tb=short', '-q']
    if args.test_path:
        pytest_cmd.append(args.test_path)
    result = subprocess.run(pytest_cmd, cwd=str(repo_root))
    tests_status = 'passed'
    if result.returncode == 5:
        tests_status = 'no tests collected'
        print('\nIMPROVE LOOP: pytest reported no tests collected; continuing because the validation run did not fail')
    elif result.returncode != 0:
        print('\nIMPROVE LOOP: tests failed — fix failing tests before committing')
        return result.returncode

    # Summary
    manifest_file = _repo_semantic_path(repo_root, MANIFEST_FILE)
    chunk_count = 0
    if manifest_file.exists():
        chunk_count = sum(1 for line in manifest_file.read_text(encoding='utf-8').splitlines() if line.strip())

    print(f'\n=== IMPROVE LOOP PASSED ===')
    print(f'  semantic chunks: {chunk_count}')
    print(f'  tests:           {tests_status}')
    print(f'  next step:       commit with `aigit commit` or `git commit`')
    return 0


def _iter_repo_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SCOUT_SKIP_DIRS]
        root_path = Path(root)
        for filename in filenames:
            path = root_path / filename
            rel = path.relative_to(repo_root)
            if any(part in SCOUT_SKIP_DIRS for part in rel.parts):
                continue
            files.append(path)
    return files


def scout_repo(repo_root: Path) -> RepoScoutSummary:
    files = _iter_repo_files(repo_root)
    python_file_count = 0
    markdown_file_count = 0
    test_file_count = 0
    total_bytes = 0
    sized_files: list[tuple[str, int]] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        suffix = path.suffix.lower()
        if suffix == '.py':
            python_file_count += 1
        if suffix == '.md':
            markdown_file_count += 1
        if rel.startswith('tests/') and suffix == '.py':
            test_file_count += 1
        size = path.stat().st_size
        total_bytes += size
        sized_files.append((rel, size))
    largest_files = sorted(sized_files, key=lambda item: item[1], reverse=True)[:5]
    if test_file_count > 0:
        recommended_tool = 'devx-quickcheck'
    else:
        recommended_tool = 'repo-health-baseline'
    recommended_interfaces = [
        'aigit improve --repo .',
        'aigit semantic-diff --base main --head HEAD --output semantic_diff.md',
        'aigit semantic-merge --base main --ours HEAD --theirs <branch> --output semantic_merge.json',
        'aigit serve-api --host 127.0.0.1 --port 8765',
    ]
    if python_file_count > 0:
        recommended_interfaces.insert(1, 'aigit chunk --repo .')
    return RepoScoutSummary(
        repo_root=repo_root,
        file_count=len(files),
        python_file_count=python_file_count,
        markdown_file_count=markdown_file_count,
        test_file_count=test_file_count,
        total_bytes=total_bytes,
        largest_files=largest_files,
        recommended_tool=recommended_tool,
        recommended_interfaces=recommended_interfaces,
    )


def _render_scout_report(summary: RepoScoutSummary) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        '# Subagent Scout Report',
        '',
        f'- generated_at_utc: `{now}`',
        f'- repo_root: `{summary.repo_root.as_posix()}`',
        '',
        '## Snapshot',
        '',
        f'- files_scanned: **{summary.file_count}**',
        f'- python_files: **{summary.python_file_count}**',
        f'- markdown_files: **{summary.markdown_file_count}**',
        f'- test_files: **{summary.test_file_count}**',
        f'- total_size_bytes: **{summary.total_bytes}**',
        '',
        '## Largest Files',
        '',
    ]
    if summary.largest_files:
        for path, size in summary.largest_files:
            lines.append(f'- `{path}` ({size} bytes)')
    else:
        lines.append('- no files discovered')
    lines.extend(
        [
            '',
            '## Diagnosis',
            '',
            '- The repository is suitable for a local verification helper that standardizes quick health checks.',
            '- Current recommendation is based on the discovered testing surface and file mix.',
            '',
            '## Tool Bootstrap Recommendation',
            '',
            f'- recommended_tool: **{summary.recommended_tool}**',
            '- proposed_tool_location: `scripts/devx_quickcheck.sh`',
            '- proposed_tool_goal: run semantic rebuild, optional lint, and tests in one command.',
            '- proposed_tool_goal: run AIGit-first quality loops through one command.',
            '',
            '## AIGit Developer Interfaces',
            '',
            '',
        ]
    )
    for interface in summary.recommended_interfaces:
        lines.append(f'- `{interface}`')
    lines.extend(
        [
            '',
            '## AI/ML Integration Hooks',
            '',
            '- Local semantic API endpoint: `GET /healthz` and `GET /chunks` via `aigit serve-api`.',
            '- Machine-readable scout output: pass `--json-output <path>` for downstream agent/tool ingestion.',
            '',
        ]
    )
    return '\n'.join(lines) + '\n'


def _scout_summary_json(summary: RepoScoutSummary) -> dict[str, Any]:
    return {
        'repo_root': summary.repo_root.as_posix(),
        'files_scanned': summary.file_count,
        'python_files': summary.python_file_count,
        'markdown_files': summary.markdown_file_count,
        'test_files': summary.test_file_count,
        'total_size_bytes': summary.total_bytes,
        'largest_files': [{'path': path, 'size_bytes': size} for path, size in summary.largest_files],
        'recommended_tool': summary.recommended_tool,
        'recommended_interfaces': summary.recommended_interfaces,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
    }


def _bootstrap_devx_quickcheck(repo_root: Path, script_path: Path) -> None:
    relative_repo = script_path.relative_to(repo_root).as_posix()
    script = (
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n\n'
        'echo "[devx-quickcheck] starting"\n'
        'python -m aigit.cli chunk --repo .\n\n'
        'if command -v aigit >/dev/null 2>&1; then\n'
        '  AIGIT_BIN="aigit"\n'
        'else\n'
        '  AIGIT_BIN="python -m aigit.cli"\n'
        'fi\n\n'
        'echo "[devx-quickcheck] refreshing semantic state"\n'
        '${AIGIT_BIN} chunk --repo .\n\n'
        'if ${AIGIT_BIN} improve --repo . "${1:-}" ; then\n'
        '  echo "[devx-quickcheck] aigit improve passed"\n'
        '  exit 0\n'
        'fi\n\n'
        'echo "[devx-quickcheck] fallback checks because improve failed or environment is partial"\n'
        'if command -v ruff >/dev/null 2>&1; then\n'
        '  echo "[devx-quickcheck] running ruff check"\n'
        '  ruff check .\n'
        'else\n'
        '  echo "[devx-quickcheck] ruff not found, skipping lint"\n'
        'fi\n\n'
        'if python - <<\'PY\'\n'
        'import importlib.util\n'
        'raise SystemExit(0 if importlib.util.find_spec("pytest") else 1)\n'
        'PY\n'
        'then\n'
        '  echo "[devx-quickcheck] running pytest"\n'
        '  python -m pytest --tb=short -q "${1:-tests}"\n'
        'else\n'
        '  echo "[devx-quickcheck] pytest missing, skipping tests"\n'
        'fi\n\n'
        'echo "[devx-quickcheck] complete"\n'
    )
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding='utf-8')
    mode = script_path.stat().st_mode
    script_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f'bootstrapped tool: {relative_repo}')


def cmd_subagent_scout(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    output_file = Path(args.output)
    if not output_file.is_absolute():
        output_file = repo_root / output_file

    print('=== Subagent Scout ===')
    print(f'scanning repository: {repo_root.as_posix()}')
    summary = scout_repo(repo_root)
    report = _render_scout_report(summary)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report, encoding='utf-8')
    print(f'wrote scout report: {output_file.relative_to(repo_root).as_posix()}')
    if args.json_output:
        json_output = Path(args.json_output)
        if not json_output.is_absolute():
            json_output = repo_root / json_output
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(_scout_summary_json(summary), indent=2) + '\n', encoding='utf-8')
        print(f'wrote scout JSON: {json_output.relative_to(repo_root).as_posix()}')

    if args.bootstrap_tool:
        script_path = repo_root / 'scripts' / 'devx_quickcheck.sh'
        if script_path.exists() and not args.force:
            print('tool bootstrap skipped: scripts/devx_quickcheck.sh already exists (use --force to overwrite)')
        else:
            _bootstrap_devx_quickcheck(repo_root, script_path)
    return 0


# ---------------------------------------------------------------------------
# Storage backend support (Git LFS / Xet)
# ---------------------------------------------------------------------------

STORAGE_BACKENDS: set[str] = {'git', 'lfs', 'xet'}

# Semantic artifact glob patterns that benefit from LFS / Xet block-level
# deduplication.  These files grow monotonically with every `aigit chunk` run.
LFS_SEMANTIC_PATTERNS: list[str] = [
    '.semantic/manifest.jsonl',
    '.semantic/edges.jsonl',
    '.semantic/chunk_index.json',
    '.semantic/provenance.jsonl',
]

GITATTRIBUTES_FILE = Path('.gitattributes')


def _probe_git_lfs() -> bool:
    """Return True when git-lfs is installed and available on PATH."""
    try:
        result = subprocess.run(
            ['git', 'lfs', 'version'],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _read_gitattributes(root: Path) -> list[str]:
    ga = root / GITATTRIBUTES_FILE
    if ga.exists():
        return ga.read_text(encoding='utf-8').splitlines()
    return []


def _write_gitattributes(root: Path, lines: list[str]) -> None:
    (root / GITATTRIBUTES_FILE).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _ensure_lfs_pattern(lines: list[str], pattern: str, filter_value: str) -> tuple[list[str], bool]:
    """Ensure *pattern* has filter=<filter_value> in .gitattributes.

    Returns the (possibly updated) lines and a bool indicating whether a change
    was made.
    """
    target = f'{pattern} filter={filter_value} diff={filter_value} merge={filter_value} -text'
    for line in lines:
        if re.match(rf'^{re.escape(pattern)}\s', line):
            return lines, False  # already tracked
    return lines + [target], True


def cmd_setup_storage(args: argparse.Namespace) -> int:
    """Configure Git LFS or Xet storage for semantic artifacts.

    ``git``  — plain Git (removes any LFS tracking for the patterns).
    ``lfs``  — Git LFS file-level deduplication.
    ``xet``  — Git LFS Xet block-level deduplication (LFS-compatible transport;
               installs the xet credential helper and sets the transfer.storage
               config key).
    """
    backend: str = args.backend
    repo_root = Path(args.repo).resolve()

    if backend == 'git':
        print('Storage backend: plain git (no LFS tracking)')
        ga = repo_root / GITATTRIBUTES_FILE
        if ga.exists():
            lines = ga.read_text(encoding='utf-8').splitlines()
            new_lines = [
                ln for ln in lines
                if not any(pat in ln for pat in LFS_SEMANTIC_PATTERNS)
            ]
            if len(new_lines) != len(lines):
                _write_gitattributes(repo_root, new_lines)
                print(f'Removed LFS tracking entries from {GITATTRIBUTES_FILE}')
        return 0

    if not _probe_git_lfs():
        print(
            'ERROR: git-lfs is not installed.  '
            'Install it from https://git-lfs.github.com/ and run `git lfs install`.'
        )
        return 1

    # Ensure LFS is initialised for this repository
    subprocess.run(['git', 'lfs', 'install'], cwd=str(repo_root), check=False, capture_output=True)

    filter_name = 'lfs'  # xet uses the same filter= value as lfs
    lines = _read_gitattributes(repo_root)
    changed = False
    for pattern in LFS_SEMANTIC_PATTERNS:
        lines, did_change = _ensure_lfs_pattern(lines, pattern, filter_name)
        changed = changed or did_change

    if changed:
        _write_gitattributes(repo_root, lines)
        print(f'Updated {GITATTRIBUTES_FILE} to track semantic artifacts via {backend.upper()}')
    else:
        print(f'{GITATTRIBUTES_FILE} already tracks semantic artifacts via {backend.upper()}')

    if backend == 'xet':
        # Xet uses its own transfer agent but identical .gitattributes syntax.
        # Set git config to opt in.
        subprocess.run(
            ['git', 'config', 'lfs.transfer.storage', 'xet'],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
        )
        print('Configured lfs.transfer.storage=xet for block-level deduplication')
        print('NOTE: Install the Xet CLI (https://github.com/xetdata/xet-tools) to activate transfer.')

    print(f'\nSemantic artifact patterns registered:')
    for pat in LFS_SEMANTIC_PATTERNS:
        print(f'  {pat}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='aigit')
    sub = parser.add_subparsers(dest='command', required=True)

    chunk = sub.add_parser('chunk', help='Generate deterministic semantic manifest')
    chunk.add_argument('--repo', default='.')
    chunk.set_defaults(func=cmd_chunk)

    diff = sub.add_parser('semantic-diff', help='Generate semantic diff report from refs')
    diff.add_argument('--base', required=True)
    diff.add_argument('--head', required=True)
    diff.add_argument('--output', default='semantic_diff.md')
    diff.set_defaults(func=cmd_diff)

    merge = sub.add_parser('semantic-merge', help='Evaluate semantic conflicts')
    merge.add_argument('--base', required=True)
    merge.add_argument('--ours', required=True)
    merge.add_argument('--theirs', required=True)
    merge.add_argument('--output', default='semantic_merge.json')
    merge.set_defaults(func=cmd_merge)

    prov = sub.add_parser('record-provenance', help='Attach AI provenance to HEAD')
    prov.add_argument('--agent', required=True)
    prov.add_argument('--model', required=True)
    prov.add_argument('--prompt', required=True)
    prov.set_defaults(func=cmd_record_provenance)

    verify_prov = sub.add_parser('verify-provenance', help='Verify AI provenance for a commit')
    verify_prov.add_argument('--ref', default='HEAD')
    verify_prov.set_defaults(func=cmd_verify_provenance)

    commit = sub.add_parser('commit', help='Commit with AI provenance trailer')
    commit.add_argument('-m', '--message', required=True)
    commit.add_argument('--agent', required=True)
    commit.add_argument('--model', required=True)
    commit.add_argument('--prompt', required=True)
    commit.set_defaults(func=cmd_commit)

    init_deerflow = sub.add_parser('init-deerflow', help='Configure deer-flow harness for autonomous development')
    init_deerflow.add_argument('--repo', default='https://github.com/bytedance/deer-flow.git')
    init_deerflow.add_argument('--skip-clone', action='store_true')
    init_deerflow.set_defaults(func=cmd_init_deerflow)

    launch_epics = sub.add_parser('launch-epics', help='Prepare the DeerFlow objective bundle for the 10-epic roadmap')
    launch_epics.add_argument('--epics-dir', default=str(EPICS_DIR))
    launch_epics.add_argument('--output-dir', default=str(DEERFLOW_OBJECTIVES_DIR))
    launch_epics.add_argument('--queue-file', default=str(DEERFLOW_QUEUE_FILE))
    launch_epics.add_argument('--repo', default='https://github.com/bytedance/deer-flow.git')
    launch_epics.add_argument('--skip-clone', action='store_true')
    launch_epics.add_argument('--bootstrap-deerflow', action='store_true')
    launch_epics.add_argument('--start-harness', action='store_true')
    launch_epics.set_defaults(func=cmd_launch_epics)

    up = sub.add_parser('up', help='Bring up the full local AIGit and DeerFlow stack')
    up.add_argument('--deerflow-repo', default='https://github.com/bytedance/deer-flow.git')
    up.add_argument('--bootstrap-deerflow', action='store_true')
    up.add_argument('--skip-clone', action='store_true')
    up.add_argument('--skip-serve-api', action='store_true')
    up.add_argument('--skip-admin-ui', action='store_true')
    up.add_argument('--api-host', default='127.0.0.1')
    up.add_argument('--api-port', type=int, default=8765)
    up.add_argument('--admin-host', default='127.0.0.1')
    up.add_argument('--admin-port', type=int, default=7860)
    up.set_defaults(func=cmd_up)

    deerflow_workspace = sub.add_parser(
        'deerflow-workspace-path',
        help='Show the host and sandbox paths for a DeerFlow thread workspace',
    )
    deerflow_workspace.add_argument('--thread-id', required=True)
    deerflow_workspace.add_argument('--workspace-subdir', default=DEERFLOW_DEFAULT_WORKSPACE_SUBDIR)
    deerflow_workspace.set_defaults(func=cmd_deerflow_workspace_path)

    deerflow_import = sub.add_parser(
        'deerflow-import-repo',
        help='Stage the current repository into a DeerFlow thread workspace',
    )
    deerflow_import.add_argument('--thread-id', required=True)
    deerflow_import.add_argument('--repo', default='.')
    deerflow_import.add_argument('--workspace-subdir', default=DEERFLOW_DEFAULT_WORKSPACE_SUBDIR)
    deerflow_import.add_argument('--exclude-git', action='store_true')
    deerflow_import.set_defaults(func=cmd_deerflow_import_repo)

    deerflow_export = sub.add_parser(
        'deerflow-export-repo',
        help='Copy DeerFlow thread workspace changes back into the local repository',
    )
    deerflow_export.add_argument('--thread-id', required=True)
    deerflow_export.add_argument('--repo', default='.')
    deerflow_export.add_argument('--workspace-subdir', default=DEERFLOW_DEFAULT_WORKSPACE_SUBDIR)
    deerflow_export.set_defaults(func=cmd_deerflow_export_repo)

    admin_ui = sub.add_parser('admin-ui', help='Launch a Gradio admin interface for DeerFlow and semantic observability')
    admin_ui.add_argument('--repo', default='.')
    admin_ui.add_argument('--host', default='127.0.0.1')
    admin_ui.add_argument('--port', type=int, default=7860)
    admin_ui.add_argument('--share', action='store_true')
    admin_ui.set_defaults(func=cmd_admin_ui)

    api = sub.add_parser('serve-api', help='Serve local chunk API')
    api.add_argument('--host', default='127.0.0.1')
    api.add_argument('--port', type=int, default=8765)
    api.set_defaults(func=serve_api)

    improve = sub.add_parser(
        'improve',
        help='Run the Codespaces-safe auto improvement loop (rebuild semantic artifacts + tests)',
    )
    improve.add_argument('--repo', default='.')
    improve.add_argument(
        '--test-path',
        dest='test_path',
        default='',
        help='Optional path to pass to pytest (e.g. tests/)',
    )
    improve.set_defaults(func=cmd_improve)

    setup_storage = sub.add_parser(
        'setup-storage',
        help='Configure Git LFS or Xet for semantic artifact storage',
    )
    setup_storage.add_argument(
        '--backend',
        choices=list(STORAGE_BACKENDS),
        default='lfs',
        help='Storage backend: git (plain), lfs (file-level dedup), xet (block-level dedup)',
    )
    setup_storage.add_argument('--repo', default='.')
    setup_storage.set_defaults(func=cmd_setup_storage)

    scout = sub.add_parser(
        'subagent-scout',
        help='Explore the repository and bootstrap a useful local dev helper tool',
    )
    scout.add_argument('--repo', default='.')
    scout.add_argument('--output', default='.aigit/runtime/subagent_scout_report.md')
    scout.add_argument('--json-output', default='.aigit/runtime/subagent_scout_report.json')
    scout.add_argument('--bootstrap-tool', action='store_true')
    scout.add_argument('--force', action='store_true', help='Overwrite an existing bootstrapped tool')
    scout.set_defaults(func=cmd_subagent_scout)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
