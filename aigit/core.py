from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import hmac
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

SEMANTIC_DIR = Path('.semantic')
MANIFEST_FILE = SEMANTIC_DIR / 'manifest.jsonl'
EDGES_FILE = SEMANTIC_DIR / 'edges.jsonl'
INDEX_FILE = SEMANTIC_DIR / 'chunk_index.json'
RULESET_FILE = SEMANTIC_DIR / 'ruleset.yaml'
SCHEMA_FILE = SEMANTIC_DIR / 'schema_version'
# Local-only (gitignored) per-file parse cache for incremental chunking.
CHUNK_CACHE_FILE = SEMANTIC_DIR / 'cache' / 'chunk_cache.json'
# Bump whenever a parser changes output or Chunk gains/changes a field:
# cached entries are rehydrated
# with ``Chunk(**record)``, so a stale entry silently backfills new fields with
# their defaults and quietly degrades everything computed from them.
CHUNK_CACHE_VERSION = '6'

SUPPORTED_PARSER_BACKENDS = {'python-ast', 'markdown-headings', 'json-keys', 'yaml-keys', 'typescript-ast', 'file'}
BINARY_ASSET_SUFFIXES = {
    '.bmp', '.gif', '.ico', '.jpeg', '.jpg', '.pdf', '.png', '.svgz', '.tif', '.tiff', '.webp',
    '.woff', '.woff2', '.zip', '.gz', '.tar', '.whl', '.wasm',
}

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
    '.aigit',
    '.deerflow',
    '.git',
    '.semantic',
    '.venv',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '__pycache__',
    'build',
    'dist',
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
    fingerprint: str = ''
    body_fingerprint: str = ''
    # Git blob id of the whole file as the parsers read it. Makes a file's
    # records differ whenever its content does, so Git hands every divergent
    # file to the merge driver, which can fetch the source by this id (see
    # parse_file).
    file_hash: str = ''

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


def _simhash(text: str) -> str:
    """Deterministic 64-bit SimHash over word tokens, as 16 hex chars.

    Uses blake2b (not Python's salted ``hash``) so the value is stable across
    processes and interpreter versions. Enables near-match (renamed + edited)
    lineage detection via Hamming distance between fingerprints.
    """
    tokens = re.findall(r'\w+', text.lower())
    if not tokens:
        return '0' * 16
    bits = [0] * 64
    for token in tokens:
        digest = hashlib.blake2b(token.encode('utf-8'), digest_size=8).digest()
        value = int.from_bytes(digest, 'big')
        for i in range(64):
            bits[i] += 1 if (value >> i) & 1 else -1
    out = 0
    for i in range(64):
        if bits[i] > 0:
            out |= (1 << i)
    return f'{out:016x}'


def _body_text(segment: str) -> str:
    """The chunk body with its declaration line removed.

    A text-only approximation for callers that have no parse tree; Python
    chunks take their body span from the AST instead, which also excludes
    decorators and multi-line signatures.

    A function's own name sits in its ``def`` line, so renaming a function
    changes its fingerprint even when the logic is untouched. Dropping that
    line yields a name-independent view, which is what duplicate-work
    detection needs to see past two agents' differing identifiers.
    """
    _, _, rest = segment.partition('\n')
    return rest


def _has_body_signal(fingerprint: Any) -> bool:
    """A body fingerprint is only evidence when the body had tokens to hash.

    ``_simhash('')`` is all zeros, and two chunks with no body at all -- stubs,
    or declaration-only chunks in older TypeScript manifests -- would then
    compare as identical. That is an absence of signal, not a match.
    """
    return bool(fingerprint) and set(str(fingerprint)) != {'0'}


def _body_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Similarity ignoring declaration lines, falling back when unavailable."""
    fa, fb = a.get('body_fingerprint'), b.get('body_fingerprint')
    if _has_body_signal(fa) and _has_body_signal(fb):
        try:
            dist = bin(int(fa, 16) ^ int(fb, 16)).count('1')
        except ValueError:
            return _chunk_similarity(a, b)
        return 1.0 - dist / 64.0
    return _chunk_similarity(a, b)


def _chunk_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Similarity in [0,1] between two chunk records: exact content first,
    then SimHash Hamming distance as a fallback."""
    if a.get('content_hash') and a.get('content_hash') == b.get('content_hash'):
        return 1.0
    fa, fb = a.get('fingerprint'), b.get('fingerprint')
    if fa and fb:
        try:
            dist = bin(int(fa, 16) ^ int(fb, 16)).count('1')
        except ValueError:
            return 0.0
        return 1.0 - dist / 64.0
    return 0.0


def parse_python(path: str, text: str, errors: list[dict[str, str]] | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        print(
            f'warning: skipping {path}: unable to parse as Python ({exc})',
            file=sys.stderr,
        )
        if errors is not None:
            errors.append({'path': path, 'error': str(exc)})
        return chunks
    lines = text.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declaration = getattr(node, 'lineno', 1)
            end = getattr(node, 'end_lineno', declaration)
            # ``node.lineno`` is the ``def``/``class`` line, so decorators sat
            # outside the chunk entirely: rewriting @app.route("/users") to
            # @app.route("/admin") left the content hash untouched and the diff
            # reported no change at all. They belong to the definition.
            start = min(
                [d.lineno for d in getattr(node, 'decorator_list', [])] + [declaration]
            )
            segment = '\n'.join(lines[start - 1 : end])
            # Fingerprint the body from the AST rather than by dropping the
            # first line: decorators and a signature spanning several lines
            # would otherwise leak into it, and the point of this fingerprint is
            # to be independent of the name the author chose.
            body_start = node.body[0].lineno if node.body else declaration
            body_segment = '\n'.join(lines[body_start - 1 : end])
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
                    fingerprint=_simhash(segment),
                    body_fingerprint=_simhash(body_segment),
                )
            )
    return chunks


def parse_markdown(path: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    lines = text.splitlines()
    header_idxs: list[int] = []
    in_fence = False
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        if not in_fence and re.match(r'^#{1,6}(?:\s+|$)', stripped):
            header_idxs.append(index)
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
    # Include the whole value section, including nested maps, sequences and
    # block scalars. A key's declaration line alone does not describe its value.
    key_pattern = re.compile(r'''^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s#\-?:][^:]*?):(?:\s|$)''')
    starts = [(i, match.group(1).strip()) for i, line in enumerate(lines)
              if (match := key_pattern.match(line))]
    if not starts:
        return parse_text(path, text)
    chunks: list[Chunk] = []
    if starts[0][0] > 0:
        chunks.extend(parse_text(path, '\n'.join(lines[:starts[0][0]])))
    for n, (start, key) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        chunks.append(Chunk(
            semantic_id=_chunk_id(path, key, 'key'), path=path,
            chunk_type='key', anchor=key,
            content_hash=_content_hash('\n'.join(lines[start:end])),
            start_line=start + 1, end_line=end, confidence='medium',
        ))
    return chunks


_TS_DECL_PATTERN = re.compile(
    r'^[ \t]*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?'
    r'(?:(?:async\s+)?function\*?\s+(\w+)|class\s+(\w+)|interface\s+(\w+)|type\s+(\w+)\s*=|(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s+)?\()',
    re.MULTILINE,
)


def _typescript_code_mask(text: str) -> str:
    """Hide literals/comments without moving offsets or line boundaries.

    This is a lexical aid to conservative section scanning, not a TS AST.
    Entire template literals are opaque; edits inside them remain in the
    original text hashed by the enclosing section.
    """
    literal = re.compile(
        r'//[^\r\n]*|/\*[\s\S]*?\*/'
        r'|"(?:\\[\s\S]|[^"\\])*"'
        r"|'(?:\\[\s\S]|[^'\\])*'"
        r'|`(?:\\[\s\S]|[^`\\])*`'
    )
    regex_literal = re.compile(r'/(?![/*])(?:\\.|\[(?:\\.|[^\]\\\r\n])*\]|[^/\\\r\n])+/[dgimsuvy]*')
    identifier = re.compile(r'[\w$]+')
    prefix_words = {'return', 'throw', 'case', 'delete', 'void', 'typeof', 'new',
                    'in', 'of', 'instanceof', 'yield', 'await'}
    masked = list(text)
    expect_operand = True
    i = 0
    while i < len(text):
        match = literal.match(text, i)
        if match is None and text[i] == '/' and expect_operand:
            match = regex_literal.match(text, i)
        if match is not None:
            raw = match.group()
            masked[i:match.end()] = ['\n' if c == '\n' else ' ' for c in raw]
            if not raw.startswith(('//', '/*')):
                expect_operand = False
            i = match.end()
            continue
        word = identifier.match(text, i)
        if word:
            expect_operand = word.group() in prefix_words
            i = word.end()
            continue
        char = text[i]
        if not char.isspace():
            if text[i:i + 2] in {'++', '--'}:
                i += 2
                continue
            expect_operand = char not in ')]}'
        i += 1
    return ''.join(masked)


def parse_typescript(path: str, text: str) -> list[Chunk]:
    """Chunk complete declaration sections with conservative lexical boundaries.

    Each section extends to the next top-level declaration or EOF. Unsupported
    syntax stays in a surrounding section or an opaque file fallback, so a
    body edit cannot disappear from the content hash.
    """
    lines = text.splitlines()
    masked = _typescript_code_mask(text)
    candidates = {m.start(): m for m in _TS_DECL_PATTERN.finditer(masked)}
    matches: list[re.Match[str]] = []
    stack: list[str] = []
    closing = {')': '(', ']': '[', '}': '{'}
    for i, char in enumerate(masked):
        if i in candidates and not stack:
            matches.append(candidates[i])
        if char in '([{':
            stack.append(char)
        elif char in closing:
            if not stack or stack.pop() != closing[char]:
                return parse_text(path, text)
    if stack or not matches:
        return parse_text(path, text)
    chunks: list[Chunk] = []
    first_line = text.count('\n', 0, matches[0].start())
    if first_line:
        chunks.extend(parse_text(path, '\n'.join(lines[:first_line])))
    for n, match in enumerate(matches):
        name = next((g for g in match.groups() if g), None)
        start_line = text.count('\n', 0, match.start()) + 1
        end_line = text.count('\n', 0, matches[n + 1].start()) if n + 1 < len(matches) else len(lines)
        segment = '\n'.join(lines[start_line - 1:end_line])
        group = next(i for i, value in enumerate(match.groups()) if value)
        chunk_type = ('function', 'class', 'interface', 'type', 'function')[group]
        chunks.append(
            Chunk(
                semantic_id=_chunk_id(path, name, chunk_type),
                path=path,
                chunk_type=chunk_type,
                anchor=name,
                content_hash=_content_hash(segment),
                start_line=start_line,
                end_line=end_line,
                confidence='medium',
                fingerprint=_simhash(segment),
            )
        )
    return chunks if chunks else parse_text(path, text)


def _disambiguate_anchors(chunks: list[Chunk]) -> list[Chunk]:
    """Give repeated ``(anchor, chunk_type)`` pairs within one file distinct ids.

    Python allows redefining a name and Markdown repeats headers freely, so one
    file can yield several chunks sharing an anchor. Chunk identity is
    ``hash(path, anchor, chunk_type)``, so those chunks collided: the manifest
    index and every semantic-id-keyed consumer (diff, merge) silently kept only
    the last occurrence, hiding the others from the merge gate entirely.

    The first occurrence keeps its original id -- manifests for files without
    repeats are byte-identical to before -- and later ones become ``anchor#2``,
    ``anchor#3``, ... so each definition is independently tracked.
    """
    seen: dict[tuple[str, str], int] = {}
    for chunk in chunks:
        key = (chunk.anchor, chunk.chunk_type)
        count = seen[key] = seen.get(key, 0) + 1
        if count > 1:
            chunk.anchor = f'{chunk.anchor}#{count}'
            chunk.semantic_id = _chunk_id(chunk.path, chunk.anchor, chunk.chunk_type)
    return chunks


def _git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b'blob %d\0' % len(data) + data, usedforsecurity=False).hexdigest()


def parse_file(full_path: Path, rel_path: str, errors: list[dict[str, str]] | None = None) -> list[Chunk]:
    """Chunk one file. Every file yields at least one chunk, and every chunk
    carries the file's hash, so the records are a one-to-one function of the
    text the parsers read: two versions of a file never share records.

    The hash is the Git blob id of that text -- line endings normalised, as
    the parsers see them, so a CRLF checkout chunks like an LF one -- which
    for an LF file is the id of the blob Git stores. The merge driver fetches
    each side's source by it, needing no knowledge of which commits Git is
    merging.

    Without that, Git merges the artifacts wrongly where no merge driver can
    intervene. Git calls a driver only when both sides' artifact blobs differ
    from each other and from the base; if two branches each insert a line
    above every chunk, both sides record the same +1 shift, Git keeps it as
    is, and the merged source -- shifted by two -- no longer matches. Likewise
    an edit a parser cannot see (an import in a file without definitions) let
    one side's records stand for a merged file they did not describe.
    """
    text = full_path.read_text(encoding='utf-8', errors='replace')
    file_hash = _git_blob_id(text.encode('utf-8'))
    suffix = full_path.suffix.lower()
    if suffix == '.py':
        parsed = parse_python(rel_path, text, errors)
    elif suffix in {'.md', '.markdown'}:
        parsed = parse_markdown(rel_path, text)
    elif suffix == '.json':
        parsed = parse_json(rel_path, text)
    elif suffix in {'.yaml', '.yml'}:
        parsed = parse_yaml(rel_path, text)
    elif suffix in {'.ts', '.tsx'}:
        parsed = parse_typescript(rel_path, text)
    else:
        parsed = parse_text(rel_path, text)
    if not parsed:
        parsed = parse_text(rel_path, text)
    for chunk in parsed:
        chunk.file_hash = file_hash
    return _disambiguate_anchors(parsed)

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
    ruleset_file = _repo_semantic_path(repo_root, RULESET_FILE)
    if not ruleset_file.is_file():
        raise ValueError(f'ruleset does not exist: {ruleset_file}')
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


def cmd_validate_ruleset(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    try:
        parsed = validate_ruleset_file(repo_root)
    except ValueError as exc:
        print(f'ruleset is invalid: {exc}', file=sys.stderr)
        return 1
    parsers = parsed['parsers']
    print(f"ruleset is valid: {len(parsers)} parser mappings")
    return 0


def _candidate_files(root: Path) -> list[Path]:
    """Files under ``root`` that a commit could contain.

    In a Git work tree that is what Git lists: tracked files plus untracked
    ones that are not ignored. Walking the directory instead let ignored local
    state -- logs, coverage reports, scratch files -- into the manifest, so
    the same commit chunked differently on different machines and the
    freshness gate failed for reasons no commit could fix.
    """
    try:
        proc = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        proc = None
    if proc is not None and proc.returncode == 0:
        names = {name for name in proc.stdout.decode('utf-8', 'surrogateescape').split('\0') if name}
        return [root / name for name in sorted(names)]
    return list(root.rglob('*'))


def _is_chunkable(rel: Path) -> bool:
    """Whether a repository path belongs in the semantic layer at all."""
    if rel.parts[0] in {'.git', '.semantic', '.deerflow'}:
        return False
    # Build products are reproducible local artifacts, not source intent.
    # Never let a package build perturb the committed semantic graph.
    if any(part in {'__pycache__', 'build', 'dist'} or part.endswith('.egg-info') for part in rel.parts):
        return False
    if any(part.startswith('.') and part != '.github' for part in rel.parts):
        return False
    return rel.suffix.lower() not in BINARY_ASSET_SUFFIXES


def iter_repo_files(root: Path) -> list[Path]:
    # Symlinks are skipped: Git stores the link, not its target, so chunking
    # the target under the link's path duplicated it, and a link leaving the
    # repository made the manifest depend on the machine.
    return sorted(
        path.relative_to(root)
        for path in _candidate_files(root)
        if path.is_file() and not path.is_symlink() and _is_chunkable(path.relative_to(root))
    )


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


def _load_chunk_cache(root: Path) -> dict[str, Any]:
    path = _repo_semantic_path(root, CHUNK_CACHE_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict) and data.get('version') == CHUNK_CACHE_VERSION:
        files = data.get('files', {})
        if isinstance(files, dict):
            return files
    return {}


def _save_chunk_cache(root: Path, files: dict[str, Any]) -> None:
    path = _repo_semantic_path(root, CHUNK_CACHE_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({'version': CHUNK_CACHE_VERSION, 'files': files}), encoding='utf-8'
        )
    except OSError:
        pass  # cache is best-effort; never fail a chunk run over it


def build_manifest(
    root: Path, errors: list[dict[str, str]] | None = None
) -> tuple[list[Chunk], list[dict[str, Any]]]:
    """Build the chunk manifest, reusing cached per-file results when a file's
    content hash is unchanged. Output is byte-identical to a full rebuild; only
    speed differs (a single-file edit no longer re-parses the whole repo).
    """
    ensure_semantic_scaffold(root)
    cache = _load_chunk_cache(root)
    new_cache: dict[str, Any] = {}
    err_sink: list[dict[str, str]] = errors if errors is not None else []
    chunks: list[Chunk] = []
    # Chunk ids are a pure function of (path, anchor, type), so a build has no
    # identity edges to record; lineage is recovered between refs at diff time.
    edges: list[dict[str, Any]] = []
    for rel in iter_repo_files(root):
        rel_str = str(rel)
        full = root / rel
        file_hash = hashlib.sha256(full.read_bytes()).hexdigest()
        cached = cache.get(rel_str)
        if cached and cached.get('file_hash') == file_hash:
            parsed = [Chunk(**record) for record in cached['chunks']]
            entry: dict[str, Any] = {'file_hash': file_hash, 'chunks': cached['chunks']}
            if cached.get('error'):
                err_sink.append({'path': rel_str, 'error': cached['error']})
                entry['error'] = cached['error']
        else:
            before = len(err_sink)
            parsed = parse_file(full, rel_str, err_sink)
            entry = {'file_hash': file_hash, 'chunks': [chunk.to_dict() for chunk in parsed]}
            if len(err_sink) > before:
                entry['error'] = err_sink[-1]['error']
        new_cache[rel_str] = entry
        chunks.extend(parsed)
    _save_chunk_cache(root, new_cache)
    return chunks, edges


def render_manifest(chunks: list[Chunk], edges: list[dict[str, Any]]) -> tuple[str, str, str]:
    """Render the (manifest, edges, index) artifact texts deterministically.

    Shared by ``write_manifest`` and ``chunk --check`` so the freshness gate
    compares exactly the bytes that would be written.
    """
    manifest_lines = [json.dumps(chunk.to_dict(), sort_keys=True) for chunk in chunks]
    manifest_text = '\n'.join(manifest_lines) + ('\n' if manifest_lines else '')
    edge_lines = [json.dumps(edge, sort_keys=True) for edge in edges]
    edges_text = '\n'.join(edge_lines) + ('\n' if edge_lines else '')
    index: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        key = f"{chunk.path}::{chunk.chunk_type}::{chunk.anchor}"
        index[key] = chunk.to_dict()
    index_text = json.dumps(index, indent=2, sort_keys=True) + '\n'
    return manifest_text, edges_text, index_text


def write_manifest(chunks: list[Chunk], edges: list[dict[str, Any]], root: Path = Path('.')) -> None:
    manifest_text, edges_text, index_text = render_manifest(chunks, edges)
    _atomic_write_text(_repo_semantic_path(root, MANIFEST_FILE), manifest_text)
    _atomic_write_text(_repo_semantic_path(root, EDGES_FILE), edges_text)
    _atomic_write_text(_repo_semantic_path(root, INDEX_FILE), index_text)


def _atomic_write_text(path: Path, text: str) -> None:
    """Publish one complete artifact; readers see the old or the new file."""
    temporary: Path | None = None
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix=f'.{path.name}.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_text_or_empty(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def cmd_chunk(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    strict = getattr(args, 'strict', False)
    check = getattr(args, 'check', False)
    errors: list[dict[str, str]] = []
    chunks, edges = build_manifest(repo_root, errors)
    manifest_text, edges_text, index_text = render_manifest(chunks, edges)

    if check:
        stale = (
            _read_text_or_empty(_repo_semantic_path(repo_root, MANIFEST_FILE)) != manifest_text
            or _read_text_or_empty(_repo_semantic_path(repo_root, INDEX_FILE)) != index_text
            or _read_text_or_empty(_repo_semantic_path(repo_root, EDGES_FILE)) != edges_text
        )
        if stale:
            print('semantic artifacts are STALE; re-run `aigit chunk`', file=sys.stderr)
            return 1
        print('semantic artifacts are up to date')
    else:
        write_manifest(chunks, edges, repo_root)
        print(f"wrote {len(chunks)} chunks and {len(edges)} lineage edges")

    if strict and errors:
        for err in errors:
            print(f"strict: unparseable file {err['path']}: {err['error']}", file=sys.stderr)
        return 1
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


def _detect_lineage(
    removed: list[dict[str, Any]],
    added: list[dict[str, Any]],
    threshold: float = 0.85,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Greedily pair removed chunks with added chunks to recover lineage.

    Returns ``(edges, unmatched_removed, unmatched_added)``. A pair is matched
    when content is identical (move/rename) or SimHash similarity clears the
    threshold (refactor). Inputs are assumed pre-sorted for determinism.
    """
    edges: list[dict[str, Any]] = []
    used_added: set[int] = set()
    used_removed: set[int] = set()
    for ri, r in enumerate(removed):
        best_sim = 0.0
        best_ai: int | None = None
        for ai, a in enumerate(added):
            if ai in used_added:
                continue
            sim = _chunk_similarity(r, a)
            if sim > best_sim:
                best_sim = sim
                best_ai = ai
        if best_ai is None or best_sim < threshold:
            continue
        a = added[best_ai]
        used_added.add(best_ai)
        used_removed.add(ri)
        moved = r.get('path') != a.get('path')
        renamed = r.get('anchor') != a.get('anchor')
        if best_sim >= 0.999:
            kind = (
                'moved+renamed' if moved and renamed
                else 'moved' if moved
                else 'renamed' if renamed
                else 'relocated'
            )
        else:
            kind = 'refactored'
        edges.append(
            {
                'from': r['semantic_id'],
                'to': a['semantic_id'],
                'kind': kind,
                'similarity': round(best_sim, 3),
                'from_loc': f"{r.get('path')}::{r.get('anchor')}",
                'to_loc': f"{a.get('path')}::{a.get('anchor')}",
            }
        )
    rem_removed = [r for i, r in enumerate(removed) if i not in used_removed]
    rem_added = [a for i, a in enumerate(added) if i not in used_added]
    return edges, rem_removed, rem_added


def compute_semantic_diff(
    base: dict[str, dict[str, Any]],
    head: dict[str, dict[str, Any]],
    lineage_threshold: float = 0.85,
) -> dict[str, Any]:
    """Pure semantic diff with lineage recovery (move/rename/refactor)."""
    added = [v for k, v in head.items() if k not in base]
    removed = [v for k, v in base.items() if k not in head]
    changed = [
        head[k]
        for k in set(base).intersection(head)
        if base[k].get('content_hash') != head[k].get('content_hash')
    ]
    sort_key = lambda c: (c.get('path', ''), c.get('anchor', ''), c.get('semantic_id', ''))
    added.sort(key=sort_key)
    removed.sort(key=sort_key)
    changed.sort(key=sort_key)
    lineage, removed, added = _detect_lineage(removed, added, lineage_threshold)
    return {'added': added, 'removed': removed, 'changed': changed, 'lineage': lineage}


def _normalize_lineage_eval_entry(entry: dict[str, Any], case_id: str) -> dict[str, Any]:
    required = ('semantic_id', 'path', 'anchor')
    missing = [field for field in required if not isinstance(entry.get(field), str) or not entry[field]]
    if missing:
        raise ValueError(f'{case_id}: fixture entry is missing {", ".join(missing)}')
    normalized = {field: entry[field] for field in required}
    content = entry.get('content')
    if isinstance(content, str):
        normalized['content_hash'] = _content_hash(content)
        normalized['fingerprint'] = _simhash(content)
    elif isinstance(entry.get('content_hash'), str):
        normalized['content_hash'] = entry['content_hash']
        normalized['fingerprint'] = str(entry.get('fingerprint', ''))
    else:
        raise ValueError(f'{case_id}: fixture entry requires content or content_hash')
    return normalized


def evaluate_lineage_fixtures(fixture_file: Path) -> dict[str, Any]:
    """Evaluate labeled lineage scenarios without reading Git state.

    Fixture entries use stable semantic IDs plus either ``content`` (preferred)
    or explicit hashes. This keeps the evaluation corpus readable while making
    the reported precision and recall reproducible from one JSON file.
    """
    try:
        payload = json.loads(fixture_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'invalid JSON fixture: {exc}') from exc
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('fixture must be an object with version: 1')
    cases = payload.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('fixture must define a non-empty cases list')

    all_expected: set[tuple[str, str, str]] = set()
    all_actual: set[tuple[str, str, str]] = set()
    case_reports: list[dict[str, Any]] = []
    for raw_case in cases:
        if not isinstance(raw_case, dict) or not isinstance(raw_case.get('id'), str):
            raise ValueError('every fixture case needs a string id')
        case_id = raw_case['id']
        raw_base = raw_case.get('base')
        raw_head = raw_case.get('head')
        raw_expected = raw_case.get('expected_lineage')
        if not all(isinstance(value, list) for value in (raw_base, raw_head, raw_expected)):
            raise ValueError(f'{case_id}: base, head, and expected_lineage must be lists')
        base = {
            entry['semantic_id']: _normalize_lineage_eval_entry(entry, case_id)
            for entry in raw_base
            if isinstance(entry, dict)
        }
        head = {
            entry['semantic_id']: _normalize_lineage_eval_entry(entry, case_id)
            for entry in raw_head
            if isinstance(entry, dict)
        }
        if len(base) != len(raw_base) or len(head) != len(raw_head):
            raise ValueError(f'{case_id}: base and head entries must be objects with unique semantic_id values')
        expected = {
            (edge.get('from'), edge.get('to'), edge.get('kind'))
            for edge in raw_expected
            if isinstance(edge, dict)
        }
        if len(expected) != len(raw_expected) or any(not all(isinstance(part, str) for part in edge) for edge in expected):
            raise ValueError(f'{case_id}: expected_lineage entries require string from, to, and kind values')
        actual = {
            (edge['from'], edge['to'], edge['kind'])
            for edge in compute_semantic_diff(base, head)['lineage']
        }
        prefixed_expected = {(case_id, *edge) for edge in expected}
        prefixed_actual = {(case_id, *edge) for edge in actual}
        all_expected.update(prefixed_expected)
        all_actual.update(prefixed_actual)
        case_reports.append(
            {
                'id': case_id,
                'expected': [
                    {'from': edge[0], 'to': edge[1], 'kind': edge[2]}
                    for edge in sorted(expected)
                ],
                'actual': [
                    {'from': edge[0], 'to': edge[1], 'kind': edge[2]}
                    for edge in sorted(actual)
                ],
                'missing': [
                    {'from': edge[1], 'to': edge[2], 'kind': edge[3]}
                    for edge in sorted(prefixed_expected - prefixed_actual)
                ],
                'unexpected': [
                    {'from': edge[1], 'to': edge[2], 'kind': edge[3]}
                    for edge in sorted(prefixed_actual - prefixed_expected)
                ],
            }
        )
    true_positive = len(all_expected & all_actual)
    false_positive = len(all_actual - all_expected)
    false_negative = len(all_expected - all_actual)
    if not all_expected:
        raise ValueError('fixture must define at least one expected lineage edge')
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    return {
        'fixture': fixture_file.as_posix(),
        'case_count': len(case_reports),
        'metrics': {
            'true_positive': true_positive,
            'false_positive': false_positive,
            'false_negative': false_negative,
            'precision': round(precision, 6),
            'recall': round(recall, 6),
        },
        'cases': case_reports,
    }


def cmd_eval_lineage(args: argparse.Namespace) -> int:
    fixture_file = Path(args.fixtures).resolve()
    try:
        report = evaluate_lineage_fixtures(fixture_file)
    except (OSError, ValueError) as exc:
        print(f'lineage evaluation failed: {exc}', file=sys.stderr)
        return 2
    output = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f'lineage evaluation written to {args.output}')
    else:
        print(output, end='')
    metrics = report['metrics']
    if metrics['precision'] < args.min_precision or metrics['recall'] < args.min_recall:
        print(
            'lineage evaluation did not meet thresholds: '
            f"precision={metrics['precision']:.3f}, recall={metrics['recall']:.3f}",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    base = _read_manifest_from_ref(args.base)
    head = _read_manifest_from_ref(args.head)
    result = compute_semantic_diff(base, head)
    added, removed, changed, lineage = (
        result['added'], result['removed'], result['changed'], result['lineage'],
    )
    report = [
        '# Semantic Diff Report',
        f'- Base: `{args.base}`',
        f'- Head: `{args.head}`',
        f'- Added: {len(added)}',
        f'- Removed: {len(removed)}',
        f'- Changed: {len(changed)}',
        f'- Moved/Renamed/Refactored: {len(lineage)}',
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
    report.append('## Moved / Renamed / Refactored')
    if not lineage:
        report.append('- None')
    else:
        for edge in sorted(lineage, key=lambda e: e['from_loc']):
            report.append(
                f"- [{edge['kind']} ~{edge['similarity']}] {edge['from_loc']} -> {edge['to_loc']}"
            )
    report.append('')
    Path(args.output).write_text('\n'.join(report), encoding='utf-8')
    print(f'wrote {args.output}')
    print(f'added={len(added)} removed={len(removed)} changed={len(changed)} lineage={len(lineage)}')
    return 0


# Matches the lineage threshold: both answer "is this the same unit of work
# under a different name?", so they are calibrated together. Applies only to
# bodies that differ; a rename alone scores 1.0 once declaration lines are
# excluded -- see the precision note in detect_duplicate_work.
DUPLICATE_WORK_THRESHOLD = 0.85
DUPLICATE_WORK_MIN_LINES = 3


def _span_lines(record: dict[str, Any]) -> int:
    try:
        return int(record.get('end_line', 0)) - int(record.get('start_line', 0)) + 1
    except (TypeError, ValueError):
        return 0


def _duplicate_score(
    a: dict[str, Any], b: dict[str, Any], threshold: float, min_lines: int
) -> float | None:
    """Score a candidate duplicate pair, or ``None`` when it fails the guards.

    A verbatim copy always counts. Otherwise the pair must carry enough
    substance to accuse, and then either share a body exactly (a pure rename,
    which counts wherever the copies live) or sit in one file and clear
    ``threshold``.
    """
    if a.get('chunk_type') != b.get('chunk_type'):
        return None
    similarity = _body_similarity(a, b)
    if a.get('content_hash') != b.get('content_hash'):
        if min(_span_lines(a), _span_lines(b)) < min_lines:
            return None
        same_file = a.get('path') == b.get('path')
        if not (similarity >= 1.0 or (same_file and similarity >= threshold)):
            return None
    return similarity


def detect_duplicate_work(
    base: dict[str, dict[str, Any]],
    ours: dict[str, dict[str, Any]],
    theirs: dict[str, dict[str, Any]],
    threshold: float = DUPLICATE_WORK_THRESHOLD,
    min_lines: int = DUPLICATE_WORK_MIN_LINES,
) -> list[dict[str, Any]]:
    """Flag work both branches added that differs in *name* but not in substance.

    ``add/add`` is keyed on ``hash(path, anchor, chunk_type)``, so it only fires
    when two agents pick the same name. Two agents solving the same ticket in
    parallel routinely pick different names -- ``pick_provider`` vs
    ``choose_provider`` -- and that duplicate work sails through the gate.

    Two passes, deliberately held to different standards because their base
    rates differ. ``scope`` on each record says which one fired.

    ``concurrent`` -- both sides added it. The comparison space is a handful of
    simultaneous additions, so near-matches are informative and are reported.

    ``existing`` -- one side added work that duplicates a chunk already present
    and *still present alongside it*. This needs no second agent, only one that
    did not know the codebase, which is the more common case. A chunk the side
    removed was renamed or moved, not duplicated, so pairing against it is
    skipped -- otherwise every rename would be reported. Only an exact body
    match counts here: measured on this repo, allowing near-matches against the
    whole corpus misfired on 8.3% of additions, because comparing against
    thousands of chunks turns up coincidental similarity far more often than
    comparing a few simultaneous ones. Requiring an exact body took that to 0%.

    Both passes compare by content rather than by name, over
    :func:`_body_similarity`, so that the identifier each agent chose does not
    itself depress the score:

    * a verbatim copy (identical ``content_hash``) is always reported;
    * otherwise the chunks must span at least ``min_lines`` -- SimHash over a
      one-liner carries too little signal to accuse two agents of duplication --
      and then either share a body exactly (a pure rename, reported wherever the
      copies live) or sit in one file and score at least ``threshold``.

    Pairing is greedy by descending similarity and each chunk is used at most
    once, so N added chunks yield at most N reports.

    Precision, measured over this repo's own chunks: excluding declaration
    lines takes a true name-only duplicate from 0.84 -- under the gate, missed
    -- to 1.0, without a meaningful change in false pairs. What it cannot fix
    is that mirror-image siblings which are *not* duplicates (say
    ``import_repo_...`` beside ``export_repo_...``) still score highly on body
    alone. Near-match reports are therefore advisory: they stop a merge for
    review the way a textual conflict does, rather than proving duplication.
    ``--no-duplicate-work`` turns the whole pass off.
    """
    ours_added = [r for sid, r in ours.items() if sid not in base and sid not in theirs]
    theirs_added = [r for sid, r in theirs.items() if sid not in base and sid not in ours]
    scored: list[tuple[float, str, str, dict[str, Any], dict[str, Any], str]] = []
    for o in ours_added:
        for t in theirs_added:
            similarity = _duplicate_score(o, t, threshold, min_lines)
            if similarity is not None:
                scored.append((similarity, o['semantic_id'], t['semantic_id'], o, t, 'concurrent'))

    # Duplicating code that was already there needs no second agent: it only
    # needs one that did not know the codebase, which is the common case. Each
    # side's additions are therefore also compared against the chunks that
    # predate them *and are still present on that side* -- a chunk the side
    # removed was renamed or moved, and pairing with it would report every
    # rename as duplicate work.
    for added, side in ((ours_added, ours), (theirs_added, theirs)):
        survivors = [r for sid, r in base.items() if sid in side]
        for new in added:
            for old in survivors:
                # Only an exact body match counts here. Measured on this repo,
                # allowing near-matches against the whole existing corpus
                # misfired on 8.3% of additions -- mirror-image siblings like
                # import_repo_/export_repo_ score 0.94, above the true
                # near-match band, so no threshold separates them. Comparing
                # against thousands of chunks has a far higher base rate of
                # coincidental similarity than comparing a handful of
                # simultaneous additions, so the bar has to be higher.
                similarity = _duplicate_score(new, old, 1.0, min_lines)
                if similarity is not None and similarity >= 1.0:
                    scored.append(
                        (similarity, new['semantic_id'], old['semantic_id'], new, old, 'existing')
                    )
    # Highest similarity first; semantic ids break ties so output is deterministic.
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    used_new: set[str] = set()
    used_match: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    for similarity, o_sid, t_sid, o, t, scope in scored:
        # One report per chunk: a new chunk that duplicates both a teammate's
        # addition and something already on trunk is still one piece of
        # duplicated work, reported against its closest match.
        if o_sid in used_new or t_sid in used_match:
            continue
        used_new.add(o_sid)
        used_match.add(t_sid)
        duplicates.append(
            {
                'semantic_id': o_sid,
                'kind': 'duplicate-work',
                'scope': scope,
                'path': o.get('path', ''),
                'anchor': o.get('anchor', ''),
                'base_hash': None,
                'ours_hash': o.get('content_hash'),
                'theirs_hash': t.get('content_hash'),
                'theirs_semantic_id': t_sid,
                'theirs_path': t.get('path', ''),
                'theirs_anchor': t.get('anchor', ''),
                'similarity': round(similarity, 4),
            }
        )
    duplicates.sort(key=lambda row: (row['semantic_id'], row['theirs_semantic_id']))
    return duplicates


def compute_semantic_conflicts(
    base: dict[str, dict[str, Any]],
    ours: dict[str, dict[str, Any]],
    theirs: dict[str, dict[str, Any]],
    include_duplicate_work: bool = True,
) -> list[dict[str, Any]]:
    """Detect semantic merge conflicts across base/ours/theirs manifests.

    A base-anchored intersection only catches modify/modify and silently
    passes the conflict classes that matter most for autonomous merges:

    * ``modify/modify`` — both sides edit the same chunk differently.
    * ``add/add``       — both sides create the same chunk with different bodies
      (two agents independently writing the same function).
    * ``modify/delete`` / ``delete/modify`` — one side edits a chunk the other
      removes.
    * ``duplicate-work`` — both sides added the same work under *different*
      names (see :func:`detect_duplicate_work`); pass
      ``include_duplicate_work=False`` to restrict the gate to name-keyed kinds.

    Returns one record per conflicting semantic id, sorted for determinism.
    """
    conflicts: list[dict[str, Any]] = []
    for sid in sorted(set(base) | set(ours) | set(theirs)):
        b = base.get(sid)
        o = ours.get(sid)
        t = theirs.get(sid)
        bh = b['content_hash'] if b else None
        oh = o['content_hash'] if o else None
        th = t['content_hash'] if t else None
        kind: str | None = None
        if b and o and t:
            if oh != bh and th != bh and oh != th:
                kind = 'modify/modify'
        elif o and t and not b:
            if oh != th:
                kind = 'add/add'
        elif b and o and not t:
            if oh != bh:
                kind = 'modify/delete'
        elif b and t and not o:
            if th != bh:
                kind = 'delete/modify'
        if kind is None:
            continue
        ref = o or t or b
        conflicts.append(
            {
                'semantic_id': sid,
                'kind': kind,
                'path': ref.get('path', ''),
                'anchor': ref.get('anchor', ''),
                'base_hash': bh,
                'ours_hash': oh,
                'theirs_hash': th,
            }
        )
    if include_duplicate_work:
        conflicts.extend(detect_duplicate_work(base, ours, theirs))
    return conflicts


def cmd_merge(args: argparse.Namespace) -> int:
    base = _read_manifest_from_ref(args.base)
    ours = _read_manifest_from_ref(args.ours)
    theirs = _read_manifest_from_ref(args.theirs)
    include_duplicate_work = not getattr(args, 'no_duplicate_work', False)
    conflicts = compute_semantic_conflicts(
        base, ours, theirs, include_duplicate_work=include_duplicate_work
    )
    out = {
        'base': args.base,
        'ours': args.ours,
        'theirs': args.theirs,
        'conflict_count': len(conflicts),
        'conflicts': conflicts,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    for c in conflicts:
        if c['kind'] == 'duplicate-work':
            relation = (
                'reimplements existing' if c.get('scope') == 'existing' else 'duplicates'
            )
            print(
                f"  conflict [duplicate-work] {c['path']}::{c['anchor']} {relation} "
                f"{c['theirs_path']}::{c['theirs_anchor']} (similarity {c['similarity']})"
            )
        else:
            print(f"  conflict [{c['kind']}] {c['path']}::{c['anchor']} ({c['semantic_id']})")
    print(f'detected {len(conflicts)} semantic conflicts')
    return 0


MERGE_DRIVER_NAME = 'aigit-semantic'
# Artifacts the merge driver understands, by file name. Chunk artifacts are a
# per-file function of the source; the others are sets of immutable records.
MERGE_DRIVER_PATTERNS: list[str] = [
    '.semantic/manifest.jsonl',
    '.semantic/chunk_index.json',
    '.semantic/edges.jsonl',
    '.semantic/provenance.jsonl',
]

ChunkRecords = list[dict[str, Any]]


def _merge_record_sets(base: str, ours: str, theirs: str) -> str:
    """Three-way merge of JSONL files whose lines are immutable records.

    A line survives when both sides kept it or either side added it, so a
    removal on one side is honoured and concurrent appends both land. This is
    exact for an append-only log: two branches recording provenance always
    collided at end of file under a text merge, though they never disagree.
    """
    o, b = (set(text.splitlines()) - {''} for text in (base, theirs))
    kept = [line for line in ours.splitlines() if line and (line in b or line not in o)]
    kept_set = set(kept)
    for line in theirs.splitlines():
        if line and line not in kept_set and line not in o:
            kept.append(line)
            kept_set.add(line)
    return ''.join(f'{line}\n' for line in kept)


def _merge_chunks_by_path(
    base: dict[str, ChunkRecords],
    ours: dict[str, ChunkRecords],
    theirs: dict[str, ChunkRecords],
    rebuild: Callable[[list[str]], dict[str, ChunkRecords]] | None = None,
    base_known: bool = True,
) -> tuple[ChunkRecords, list[str]]:
    """Three-way merge of chunk records, with each source file as the unit.

    A file's chunks are a function of that file alone and carry its hash, so
    unchanged chunks mean an unchanged file: when only one side changed a
    file's chunks, that side's chunks are exactly what a rebuild of the merged
    source yields. A text merge has no such unit: line numbers make one edit
    rewrite every later chunk in its file, so two edits to one file conflicted
    even when Git merged the source cleanly, and occasionally merged
    "cleanly" into line numbers that were wrong.

    When both sides changed a file's chunks, no merge of the records can be
    trusted: content hashes of the merged source exist on neither side, and
    even identical sides are suspect because line numbers are offsets -- two
    edits that each shift a chunk by one shift it by two together. Those paths
    go to ``rebuild``, which re-chunks the merged source; any it cannot resolve
    keep ours and are returned so the caller reports a conflict.

    Without base records (``base_known`` false: the artifacts did not exist at
    the merge base, as when two branches adopt AIGit separately) "unchanged
    since base" cannot be told from "added" or "deleted", so every path the
    two sides disagree on is contested.
    """
    by_path: dict[str, ChunkRecords] = {}
    contested: list[str] = []
    for path in set(base) | set(ours) | set(theirs):
        o, a, b = base.get(path, []), ours.get(path, []), theirs.get(path, [])
        if not base_known:
            by_path[path] = a
            if a != b:
                contested.append(path)
        elif a == o:
            by_path[path] = b
        elif b == o:
            by_path[path] = a
        else:
            by_path[path] = a
            contested.append(path)
    contested.sort()
    resolved = rebuild(contested) if rebuild and contested else {}
    by_path.update(resolved)
    merged = [record for path in sorted(by_path, key=Path) for record in by_path[path]]
    return merged, [path for path in contested if path not in resolved]


def _group_by_path(records: ChunkRecords) -> dict[str, ChunkRecords]:
    grouped: dict[str, ChunkRecords] = {}
    for record in records:
        grouped.setdefault(str(record.get('path', '')), []).append(record)
    return grouped


def merge_semantic_artifact(
    name: str,
    base: str,
    ours: str,
    theirs: str,
    rebuild: Callable[..., dict[str, ChunkRecords]] | None = None,
) -> tuple[str, list[str]]:
    """Merge one ``.semantic`` artifact; returns ``(text, paths_needing_rebuild)``.

    ``rebuild(paths, base, ours, theirs, base_known=...)`` re-chunks the
    merged source of files both sides changed (see
    ``rebuild_from_merged_source``). Raises ``ValueError`` for an artifact it
    does not handle or cannot parse.
    """
    if name in {'edges.jsonl', 'provenance.jsonl'}:
        return _merge_record_sets(base, ours, theirs), []
    if name == 'manifest.jsonl':
        records = [
            [json.loads(line) for line in text.splitlines() if line.strip()]
            for text in (base, ours, theirs)
        ]
    elif name == 'chunk_index.json':
        records = [list(json.loads(text).values()) if text.strip() else [] for text in (base, ours, theirs)]
    else:
        raise ValueError(f'no semantic merge rule for {name}')
    sides = [_group_by_path(side) for side in records]
    base_known = bool(records[0]) or not (records[1] or records[2])
    bound = (lambda paths: rebuild(paths, *sides, base_known=base_known)) if rebuild else None
    merged, needs_rebuild = _merge_chunks_by_path(*sides, rebuild=bound, base_known=base_known)
    if name == 'manifest.jsonl':
        lines = [json.dumps(record, sort_keys=True) for record in merged]
        return '\n'.join(lines) + ('\n' if lines else ''), needs_rebuild
    index = {f"{r['path']}::{r['chunk_type']}::{r['anchor']}": r for r in merged}
    return json.dumps(index, indent=2, sort_keys=True) + '\n', needs_rebuild


def _git_output(args: list[str], cwd: Path) -> bytes | None:
    proc = subprocess.run(['git', *args], cwd=cwd, capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def _commit_ids(cwd: Path, revs: list[str]) -> list[str]:
    seen: list[str] = []
    for rev in revs:
        out = _git_output(['rev-parse', '-q', '--verify', f'{rev}^{{commit}}'], cwd)
        sha = out.decode().strip() if out else ''
        if sha and sha not in seen:
            seen.append(sha)
    return seen


_PICK_COMMANDS = {'pick', 'p', 'reword', 'r', 'edit', 'e', 'squash', 's', 'fixup', 'f'}


def _merge_in_progress(cwd: Path) -> tuple[str, list[str], list[str]]:
    """``(ours, [theirs], bases)``: the commits Git is merging, and the merge base(s).

    Git does not hand a merge driver its commits; each operation leaves them
    somewhere else. A merge exports ``GITHEAD_<sha>``; a rebase lists the
    current pick last in ``rebase-merge/done``; a cherry-pick, revert or stash
    names its commit on the command line of the Git process that started
    this one, and ``git merge-tree --write-tree A B`` -- what merge queues run,
    with no work tree and ``HEAD`` beside the point -- names both sides. Ours
    is ``HEAD`` except there. Only the exact commit is returned, never a list of plausible
    ones: the chunks of a stale artifact match *some* commit -- typically the
    parent of the one being merged -- and accepting that would chunk the
    wrong source. Where the commit cannot be pinned down (``git am``, an
    octopus, a range of cherry-picks) none is returned, and sources are read
    by blob id instead.
    """
    args = _git_parent_args() or []
    operation = _git_operation(args)
    named = [arg for arg in args[2:] if not arg.startswith('-') and arg != operation]

    def parents(commit: str) -> list[str]:
        return (_git_output(['rev-parse', f'{commit}^@'], cwd) or b'').decode().split()

    ours = 'HEAD'
    theirs: list[str] = []
    bases: list[str] = []
    if operation == 'merge-tree':
        sides, merge_base = [], None
        values = iter(args[args.index('merge-tree') + 1:])
        for arg in values:
            if arg == '--merge-base':
                merge_base = next(values, None)
            elif arg.startswith('--merge-base='):
                merge_base = arg.split('=', 1)[1]
            elif arg in {'-X', '--strategy-option'}:
                next(values, None)
            elif not arg.startswith('-'):
                sides.append(arg)
        if '--write-tree' in args and '--stdin' not in args and len(sides) == 2:
            pinned = [_commit_ids(cwd, [side]) for side in sides]
            if all(pinned):
                ours, theirs = pinned[0][0], pinned[1]
                bases = _commit_ids(cwd, [merge_base]) if merge_base else (
                    _git_output(['merge-base', '--all', ours, theirs[0]], cwd) or b''
                ).decode().split()
    elif operation in {'merge', 'pull'}:
        heads = [key[len('GITHEAD_'):] for key in os.environ if key.startswith('GITHEAD_')]
        theirs = _commit_ids(cwd, heads) if len(heads) == 1 else []
        if theirs:
            bases = (_git_output(['merge-base', '--all', 'HEAD', theirs[0]], cwd) or b'').decode().split()
    elif operation == 'rebase':
        git_dir = (_git_output(['rev-parse', '--git-dir'], cwd) or b'').decode().strip()
        try:
            done = (cwd / git_dir / 'rebase-merge' / 'done').read_text(encoding='utf-8').split('\n')
        except OSError:
            done = []
        last = next((line.split() for line in reversed(done) if line.strip()), [])
        if len(last) > 1 and last[0] in _PICK_COMMANDS:
            theirs = _commit_ids(cwd, [last[1]])
            bases = parents(theirs[0]) if theirs else []
    elif operation in {'cherry-pick', 'revert'} and len(named) == 1 and '..' not in named[0]:
        picked = _commit_ids(cwd, named)
        if picked and operation == 'cherry-pick':
            theirs, bases = picked, parents(picked[0])
        elif picked and len(parents(picked[0])) == 1:
            theirs, bases = parents(picked[0]), picked  # a revert merges in reverse
    elif operation == 'stash':
        refs = [arg for arg in named if arg not in {'pop', 'apply'}] or ['refs/stash']
        stash = _commit_ids(cwd, refs[:1])
        if stash:
            theirs, bases = stash, parents(stash[0])[:1]
    if len(theirs) != 1 or not bases:
        return ours, [], []
    return ours, theirs, bases


def _chunk_records_for_source(path: str, data: bytes | None) -> ChunkRecords:
    if data is None:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        # Only the suffix picks the parser; the name comes from another
        # branch's artifact and is not trusted as a file name.
        source = Path(tmp) / f'source{Path(path).suffix}'
        source.write_bytes(data)
        return [chunk.to_dict() for chunk in parse_file(source, path)]


def _canonical(records: ChunkRecords) -> list[str]:
    # The manifest keeps a file's chunks in source order, the index by key.
    return sorted(json.dumps(record, sort_keys=True) for record in records)


_OBJECT_ID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')


def _source_matching(
    cwd: Path, commits: list[str], path: str, records: ChunkRecords
) -> tuple[bool, str | None, bytes | None]:
    """``(found, commit, source)`` of ``path`` on the side whose chunks are ``records``.

    The source counts only if chunking it reproduces ``records`` exactly; no
    records means the file is absent on that side, which is checked too. It is
    read from the given commits, which exposes artifacts that are stale
    against their commit. With no commit to read -- ``git am``, or a
    cherry-pick of a range -- it is read by the blob id the chunks name; an
    artifact already stale in the applied commit then carries over, as it
    would through a text merge, for the freshness gate to catch. ``commit`` is
    the commit the source came from, when it came from one.
    """
    if not records:
        present = any(_git_output(['cat-file', '-e', f'{commit}:{path}'], cwd) is not None for commit in commits)
        return (not present), None, None
    expected = _canonical(records)
    if commits:
        for commit in commits:
            data = _git_output(['cat-file', 'blob', f'{commit}:{path}'], cwd)
            if data is not None and _canonical(_chunk_records_for_source(path, data)) == expected:
                return True, commit, data
        return False, None, None
    blob_ids = {str(record.get('file_hash', '')) for record in records}
    blob_id = blob_ids.pop() if len(blob_ids) == 1 else ''
    if _OBJECT_ID.fullmatch(blob_id):  # never let artifact data reach git as an option
        data = _git_output(['cat-file', 'blob', blob_id], cwd)
        if data is not None and _canonical(_chunk_records_for_source(path, data)) == expected:
            return True, None, data
    return False, None, None


def _commit_with(cwd: Path, commits: list[str], path: str, data: bytes | None) -> str | None:
    """The first of ``commits`` holding exactly ``data`` at ``path`` (None: no such file)."""
    for commit in commits:
        if _git_output(['cat-file', 'blob', f'{commit}:{path}'], cwd) == data:
            return commit
    return None


def _renamed_to(cwd: Path, base_commit: str, side_commit: str, path: str) -> str | None:
    """Where ``side_commit`` renamed ``path``, by the rename detection Git merges with."""
    out = _git_output(['diff', '--name-status', '-M', '-z', base_commit, side_commit], cwd)
    fields = out.decode('utf-8', 'surrogateescape').split('\0') if out else []
    targets: list[str] = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status[:1] in {'R', 'C'}:
            if status[:1] == 'R' and fields[i + 1] == path:
                targets.append(fields[i + 2])
            i += 3
        else:
            i += 2
    return targets[0] if len(targets) == 1 else None


# Inherited Git settings a throwaway repository must not see: they name the
# repository being merged. Configuration (``git -c``) is kept.
_GIT_ENV_KEPT = ('GIT_CONFIG', 'GIT_EXEC_PATH')


def _merge_like_git(jobs: dict[str, tuple[bytes, bytes | None, bytes]]) -> dict[str, bytes | None]:
    """Merge three versions of each file exactly as ``git merge`` would.

    ``jobs`` maps a key to ``(ours, base, theirs)`` (base None: added on both
    sides); the result maps it to the merged bytes, or None on conflict.

    ``git merge-file`` is not that: it diffs with Myers, while the ort
    strategy behind merge, rebase and cherry-pick hard-codes histogram, and
    on 400 random three-way merges they disagreed 8 times -- twice both
    merging cleanly into different text, which would have been chunked as if
    Git had produced it. So the files go through ort itself, all in one merge
    in a throwaway repository, under the user's configuration.
    """
    results: dict[str, bytes | None] = dict.fromkeys(jobs)
    if not jobs:
        return results
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT') or k.startswith(_GIT_ENV_KEPT)}
    env.update(
        GIT_AUTHOR_NAME='aigit', GIT_AUTHOR_EMAIL='aigit@localhost',
        GIT_COMMITTER_NAME='aigit', GIT_COMMITTER_EMAIL='aigit@localhost',
    )
    names = {f'f{i}': key for i, key in enumerate(jobs)}
    with tempfile.TemporaryDirectory() as tmp:
        hooks = Path(tmp) / 'no-hooks'
        hooks.mkdir()

        def git(*args: str, data: bytes = b'') -> subprocess.CompletedProcess:
            return subprocess.run(
                [
                    'git', '-c', f'core.hooksPath={hooks}', '-c', 'commit.gpgSign=false',
                    '-c', 'core.fsmonitor=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', *args,
                ],
                cwd=tmp, env=env, input=data, capture_output=True, check=False,
            )

        def commit(side: int, parent: str | None = None) -> str:
            entries = []
            for name, key in names.items():
                data = jobs[key][side]
                if data is not None:
                    blob = git('hash-object', '-w', '--no-filters', '--stdin', data=data).stdout.decode().strip()
                    entries.append(f'100644 blob {blob}\t{name}\n')
            tree = git('mktree', data=''.join(entries).encode()).stdout.decode().strip()
            return git('commit-tree', tree, *(['-p', parent] if parent else []), '-m', 'x').stdout.decode().strip()

        if git('init', '-q', '--template=').returncode != 0:
            return results
        base_commit = commit(1)
        ours_commit, theirs_commit = commit(0, base_commit), commit(2, base_commit)
        if git('checkout', '-q', ours_commit).returncode != 0:
            return results
        if git('merge', '-q', '--no-commit', '--no-ff', '-s', 'ort', theirs_commit).returncode not in {0, 1}:
            return results
        for line in git('ls-files', '-s', '-z').stdout.decode().split('\0'):
            meta, _, name = line.partition('\t')
            fields = meta.split()
            if name in names and len(fields) == 3 and fields[2] == '0':
                merged = git('cat-file', 'blob', fields[1])
                if merged.returncode == 0:
                    results[names[name]] = merged.stdout
    return results


def _plain_text_merge(cwd: Path, path: str) -> bool:
    attr = (_git_output(['check-attr', 'merge', '--', path], cwd) or b'').decode()
    return attr.rsplit(':', 1)[-1].strip() in {'unspecified', 'set'}


def _process_parent_and_args(pid: int) -> tuple[int, list[str]] | None:
    """``(parent pid, argv)`` of a process: /proc, then ``ps``, then Windows CIM."""
    try:
        stat_line = Path(f'/proc/{pid}/stat').read_text(encoding='utf-8')
        args = Path(f'/proc/{pid}/cmdline').read_bytes().decode('utf-8', 'replace').split('\0')
        return int(stat_line.rsplit(')', 1)[1].split()[1]), [arg for arg in args if arg]
    except (OSError, ValueError, IndexError):
        pass
    if os.name == 'nt':
        query = (
            f'$p = Get-CimInstance Win32_Process -Filter "ProcessId={pid}"; '
            'if ($p) { $p.ParentProcessId; $p.CommandLine }'
        )
        command = ['powershell', '-NoProfile', '-NonInteractive', '-Command', query]
    else:
        command = ['ps', '-o', 'ppid=,args=', '-p', str(pid)]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    if os.name == 'nt':
        lines = proc.stdout.splitlines()
        if proc.returncode != 0 or len(lines) < 2:
            return None
        parent, cmdline = lines[0].strip(), lines[1]
        args = [arg.strip('"') for arg in shlex.split(cmdline, posix=False)]
    else:
        fields = proc.stdout.split()
        if proc.returncode != 0 or not fields:
            return None
        parent, args = fields[0], fields[1:]
    try:
        return int(parent), args
    except ValueError:
        return None


def _git_parent_args() -> list[str] | None:
    """Arguments of the nearest Git process above this one, if it can be read."""
    pid = os.getppid()
    for _ in range(6):
        found = _process_parent_and_args(pid)
        if found is None:
            return None
        parent, args = found
        if args and Path(args[0]).name.lower() in {'git', 'git.exe'}:
            return args
        if parent <= 1:
            return None
        pid = parent
    return None


# Options whose value is a separate argument that may itself look like a flag.
_VALUE_OPTIONS = {'-m', '--message', '-F', '--file', '-c', '-C', '--exec', '--onto', '--into-name'}


def _strategy_overrides(args: list[str]) -> bool:
    """Whether Git arguments pick a strategy other than ort, or any -X option."""
    values = iter(args)
    for arg in values:
        if arg in _VALUE_OPTIONS:
            next(values, None)
        elif arg in {'-s', '--strategy'}:
            if next(values, None) != 'ort':
                return True
        elif arg.startswith('--strategy='):
            if arg.split('=', 1)[1] != 'ort':
                return True
        elif arg.startswith('-s') and not arg.startswith('--'):
            if arg[2:] != 'ort':
                return True
        elif arg in {'-X', '--strategy-option'} or arg.startswith(('-X', '--strategy-option=')):
            return True
    return False


def _merge_is_overridden(cwd: Path) -> bool:
    """Whether Git may merge file content differently from a plain ort merge.

    ``-X ignore-space-change``, ``-X ours``, another strategy (``-s``,
    ``pull.twohead``) or ``merge.renormalize`` change Git's result, and none
    reaches a merge driver, so they are read off the Git process that started
    this one. If that process cannot be read, nothing is assumed: the driver
    declines and asks for ``aigit chunk``. A false alarm only costs that.
    """
    renormalize = (_git_output(['config', '--bool', 'merge.renormalize'], cwd) or b'').strip()
    twohead = (_git_output(['config', 'pull.twohead'], cwd) or b'').strip()
    if renormalize == b'true' or twohead not in {b'', b'ort'}:
        return True
    args = _git_parent_args()
    return args is None or _strategy_overrides(args[1:])


_OPERATIONS = {'merge', 'merge-tree', 'pull', 'rebase', 'cherry-pick', 'revert', 'stash', 'am'}


def _git_operation(args: list[str]) -> str | None:
    """The Git subcommand in a Git command line (``git -c k=v merge x`` -> merge)."""
    values = iter(args[1:])
    for arg in values:
        if arg in _VALUE_OPTIONS:
            next(values, None)
        elif not arg.startswith('-'):
            return arg if arg in _OPERATIONS else None
    return None


def rebuild_from_merged_source(
    cwd: Path,
    paths: list[str],
    base: dict[str, ChunkRecords],
    ours: dict[str, ChunkRecords],
    theirs: dict[str, ChunkRecords],
    base_known: bool = True,
) -> dict[str, ChunkRecords]:
    """Re-chunk files both sides changed, from the source Git is merging.

    Each side's source is accepted only if chunking it reproduces that side's
    committed chunks -- exact, since chunks carry the file's blob id -- so
    artifacts stale against their commit decline rather than guess. Without
    base artifacts the base source is read from the commit Git merges against.
    The merged source comes from Git's own ort merge of the three versions. A
    file one side renamed and the other edited is merged at its new path, as
    Git does; renamed out of the chunked set, it leaves the artifacts. A
    source conflict, a modify/delete, a custom merge attribute, or merge
    options that change Git's file merge decline: Git's result there is not
    ours to reproduce.
    """
    resolved: dict[str, ChunkRecords] = {}
    if _merge_is_overridden(cwd):
        return resolved
    ours_commit, theirs_commits, base_commits = _merge_in_progress(cwd)
    exact_base = None
    if not base_known:
        if len(base_commits) != 1:
            return resolved
        exact_base = base_commits[0]
    jobs: dict[str, tuple[bytes, bytes | None, bytes]] = {}
    origin: dict[str, str] = {}
    for path in paths:
        ok_ours, _, src_ours = _source_matching(cwd, [ours_commit], path, ours.get(path, []))
        ok_theirs, _, src_theirs = _source_matching(cwd, theirs_commits, path, theirs.get(path, []))
        if exact_base:
            ok_base, src_base = True, _git_output(['cat-file', 'blob', f'{exact_base}:{path}'], cwd)
        else:
            ok_base, _, src_base = _source_matching(cwd, base_commits, path, base.get(path, []))
        if not (ok_ours and ok_theirs and ok_base):
            continue
        if src_ours is None and src_theirs is None:
            resolved[path] = []
            continue
        target = path
        if src_ours is None or src_theirs is None:
            present, present_side = (src_theirs, theirs) if src_ours is None else (src_ours, ours)
            if src_base is None:
                resolved[path] = present_side.get(path, [])  # added on one side only
                continue
            if present == src_base:
                resolved[path] = []  # deleted on one side, untouched on the other
                continue
            # Otherwise a rename, if Git pairs the file with a new path; that
            # needs both commits to ask. Failing that, a modify/delete.
            gone_side, kept_side = (ours, theirs) if src_ours is None else (theirs, ours)
            gone_commit = ours_commit if src_ours is None else _commit_with(cwd, theirs_commits, path, None)
            base_commit = exact_base or _commit_with(cwd, base_commits, path, src_base)
            if gone_commit is None or base_commit is None:
                continue
            target = _renamed_to(cwd, base_commit, gone_commit, path) or ''
            if not target or kept_side.get(target):
                continue
            if not _is_chunkable(Path(target)):
                resolved[path] = []  # renamed out of the semantic layer
                continue
            found, _, moved = _source_matching(cwd, [gone_commit], target, gone_side.get(target, []))
            if not found or moved is None:
                continue
            src_ours, src_theirs = (moved, src_theirs) if src_ours is None else (src_ours, moved)
        if not (_plain_text_merge(cwd, path) and _plain_text_merge(cwd, target)):
            continue
        jobs[target] = (src_ours, src_base, src_theirs)
        origin[target] = path
    for target, merged in _merge_like_git(jobs).items():
        if merged is None:
            continue
        if origin[target] != target:
            resolved[origin[target]] = []
        resolved[target] = _chunk_records_for_source(target, merged)
    return resolved


def cmd_merge_driver(args: argparse.Namespace) -> int:
    """Git merge driver entry point: ``aigit merge-driver %O %A %B %P``.

    Writes the result to %A. Exits 1 -- a conflict Git will report -- only when
    a file both sides changed could not be re-chunked from the merged source.
    """
    name = Path(args.path or args.ours).name
    cwd = Path.cwd()
    rebuild = lambda paths, *sides, **kw: rebuild_from_merged_source(cwd, paths, *sides, **kw)
    try:
        base, ours, theirs = (
            Path(p).read_text(encoding='utf-8') for p in (args.base, args.ours, args.theirs)
        )
        merged, needs_rebuild = merge_semantic_artifact(name, base, ours, theirs, rebuild=rebuild)
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        # Artifacts are data from another branch; anything malformed is a
        # conflict to resolve with `aigit chunk`, never a crash mid-merge.
        print(f'aigit merge-driver: cannot merge {args.path or name} ({exc}); leaving ours', file=sys.stderr)
        return 1
    Path(args.ours).write_text(merged, encoding='utf-8')
    if needs_rebuild:
        print(
            f'aigit merge-driver: {args.path or name}: chunks changed on both sides for '
            f"{', '.join(needs_rebuild)}; run `aigit chunk` and stage .semantic/",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_install_merge_driver(args: argparse.Namespace) -> int:
    """Register the merge driver in this clone and route artifacts to it."""
    repo_root = Path(args.repo).resolve()
    command = f'{shlex.quote(sys.executable)} -m aigit.cli merge-driver %O %A %B %P'
    _run_git(['config', f'merge.{MERGE_DRIVER_NAME}.name', 'AIGit semantic artifact merge'], cwd=repo_root)
    _run_git(['config', f'merge.{MERGE_DRIVER_NAME}.driver', command], cwd=repo_root)
    lines = _read_gitattributes(repo_root)
    added = []
    routed = []
    for pattern in MERGE_DRIVER_PATTERNS:
        existing = [line for line in lines if re.match(rf'^{re.escape(pattern)}\s', line)]
        if any('merge=' in line and f'merge={MERGE_DRIVER_NAME}' not in line for line in existing):
            # A path has one merge attribute; LFS pointers are not records we can merge.
            print(f'skipped {pattern}: it already names another merge driver in {GITATTRIBUTES_FILE}')
            continue
        routed.append(f'{pattern} merge={MERGE_DRIVER_NAME}')
        if not existing:
            lines.append(routed[-1])
            added.append(pattern)
    if added:
        _write_gitattributes(repo_root, lines)
        print(f'routed {len(added)} semantic artifacts to the merge driver in {GITATTRIBUTES_FILE}')
    # Git reads .gitattributes from the branch being merged into, so a branch
    # cut before the routing was committed would merge the artifacts as text.
    # info/attributes applies to every branch in this clone.
    info = repo_root / _run_git(['rev-parse', '--git-path', 'info/attributes'], cwd=repo_root)
    present = info.read_text(encoding='utf-8').splitlines() if info.exists() else []
    missing = [line for line in routed if line not in present]
    if missing:
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text(''.join(f'{line}\n' for line in present + missing), encoding='utf-8')
    print(f'registered merge.{MERGE_DRIVER_NAME}.driver for this clone')
    return 0


def _provenance_key() -> str | None:
    """Secret HMAC key for provenance signing, from AIGIT_PROVENANCE_KEY."""
    return os.environ.get('AIGIT_PROVENANCE_KEY') or None


def _validate_provenance_identity(agent: str, model: str) -> None:
    # These values appear in both newline-delimited HMACs and semicolon-
    # delimited trailers. Reject ambiguous encodings before any write/commit.
    for field, value in (('agent', agent), ('model', model)):
        if (not isinstance(value, str) or not value or value != value.strip()
                or ';' in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(f'provenance {field} must be a nonempty identity without whitespace padding, control characters or semicolons')


def _provenance_signature(key: str, commit: str, agent: str, model: str, prompt_hash: str) -> str:
    """HMAC-SHA256 over the immutable provenance claim, binding it to a commit.

    Without the key the signature cannot be reproduced, so a forged plaintext
    log row will not validate under ``verify-provenance --require-signature``.
    """
    _validate_provenance_identity(agent, model)
    message = '\n'.join([commit, agent, model, prompt_hash]).encode('utf-8')
    return hmac.new(key.encode('utf-8'), message, hashlib.sha256).hexdigest()


def cmd_record_provenance(args: argparse.Namespace) -> int:
    _validate_provenance_identity(args.agent, args.model)
    repo_root = Path('.').resolve()
    ensure_semantic_scaffold(repo_root)
    commit = _run_git(['rev-parse', 'HEAD'])
    prompt_hash = _hash([args.prompt])
    row = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'commit': commit,
        'agent': args.agent,
        'model': args.model,
        'prompt_hash': prompt_hash,
    }
    key = _provenance_key()
    if key:
        row['signature'] = _provenance_signature(key, commit, args.agent, args.model, prompt_hash)
    path = _repo_semantic_path(repo_root, SEMANTIC_DIR / 'provenance.jsonl')
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, sort_keys=True) + '\n')
    signed_note = ' (signed)' if key else ' (unsigned: set AIGIT_PROVENANCE_KEY to sign)'
    print(f'appended provenance to {path}{signed_note}')
    return 0


def _parse_provenance_trailer(message: str) -> dict[str, str] | None:
    trailers = [line[len('AI-Provenance:'):].strip() for line in message.splitlines()
                if line.startswith('AI-Provenance:')]
    if not trailers:
        return None
    if len(trailers) != 1:
        raise ValueError('commit has multiple AI-Provenance trailers')
    fields: dict[str, str] = {}
    for part in trailers[0].split(';'):
        if '=' not in part:
            raise ValueError('invalid AI-Provenance trailer field')
        key, value = part.split('=', 1)
        key = key.strip()
        if key in fields:
            raise ValueError(f'duplicate AI-Provenance field: {key}')
        fields[key] = value.strip()
    if set(fields) != {'agent', 'model', 'prompt-hash'}:
        raise ValueError('AI-Provenance requires agent, model and prompt-hash fields')
    _validate_provenance_identity(fields['agent'], fields['model'])
    if not re.fullmatch(r'[0-9a-fA-F]{16,64}', fields['prompt-hash']):
        raise ValueError('AI-Provenance prompt-hash must contain 16 to 64 hex characters')
    return fields


def verify_provenance(ref: str = 'HEAD', repo_root: Path = Path('.')) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    commit = _run_git(['rev-parse', ref], cwd=repo_root)
    message = _run_git(['show', '-s', '--format=%B', commit], cwd=repo_root)
    trailer = _parse_provenance_trailer(message)
    if trailer is None:
        raise ValueError(f'{commit} is missing an AI-Provenance trailer')

    provenance_path = _repo_semantic_path(repo_root, SEMANTIC_DIR / 'provenance.jsonl')
    rows = _read_jsonl_rows(provenance_path, strict=True)
    commit_rows = [row for row in rows if row.get('commit') == commit]
    if not commit_rows:
        raise ValueError(f'no provenance log row found for commit {commit}')
    matching_rows = [row for row in commit_rows
                     if row.get('agent') == trailer['agent'] and row.get('model') == trailer['model']
                     and isinstance(row.get('prompt_hash'), str)
                     and re.fullmatch(r'[0-9a-fA-F]{64}', row['prompt_hash'])
                     and row['prompt_hash'].lower().startswith(trailer['prompt-hash'].lower())]
    if not matching_rows:
        raise ValueError(f'provenance trailer does not match log row for commit {commit}')
    if len({row['prompt_hash'].lower() for row in matching_rows}) != 1:
        raise ValueError(f'ambiguous provenance prompt-hash prefix for commit {commit}')

    key = _provenance_key()
    matching_row = matching_rows[-1]
    signed = False
    if key:
        for candidate in reversed(matching_rows):
            signature = candidate.get('signature')
            expected = _provenance_signature(key, commit, candidate['agent'], candidate['model'], candidate['prompt_hash'])
            if isinstance(signature, str) and re.fullmatch(r'[0-9a-fA-F]{64}', signature) and hmac.compare_digest(expected, signature.lower()):
                matching_row, signed = candidate, True
                break

    return {
        'commit': commit,
        'trailer': trailer,
        'log_row': matching_row,
        'provenance_path': str(provenance_path),
        'signed': signed,
    }


def cmd_verify_provenance(args: argparse.Namespace) -> int:
    try:
        result = verify_provenance(ref=args.ref, repo_root=Path('.'))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, 'require_signature', False) and not result.get('signed'):
        print(f"provenance for {result['commit']} is not validly signed", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    _validate_provenance_identity(args.agent, args.model)
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


def _read_jsonl_rows(path: Path, *, strict: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        if strict:
            raise ValueError(f'cannot read JSONL log: {path}') from exc
        raise
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f'invalid JSONL record at {path}:{number}') from exc
            continue
        if isinstance(value, dict):
            rows.append(value)
        elif strict:
            raise ValueError(f'JSONL record must be an object at {path}:{number}')
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

        launch_admin_ui(repo_root=Path(args.repo).resolve(), host=args.host, port=args.port, share=args.share)
    except ImportError as exc:
        print(f'admin UI requires the optional "ui" extra (Gradio): {exc}', file=sys.stderr)
        print('install it with:  python -m pip install "aigit[ui]"', file=sys.stderr)
        return 1
    return 0


def _filter_paginate(
    chunks: list[dict[str, Any]],
    path_prefix: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Filter chunks by path prefix and apply offset/limit. Returns (page, total)."""
    items = (
        chunks
        if not path_prefix
        else [c for c in chunks if str(c.get('path', '')).startswith(path_prefix)]
    )
    total = len(items)
    start = max(offset, 0)
    page = items[start:] if limit is None else items[start:start + max(limit, 0)]
    return page, total


def serve_api(args: argparse.Namespace) -> int:
    manifest_file = _repo_semantic_path(Path('.').resolve(), MANIFEST_FILE)
    # Hash actual bytes on every request: size/mtime can repeat after a restore
    # or same-size edit. Parse/serialize only on a content change and publish
    # one snapshot under a lock so body, rows and validator cannot be mixed.
    cache: tuple[list[dict[str, Any]], str, bytes] | None = None
    cache_lock = threading.Lock()

    def _load() -> tuple[list[dict[str, Any]], str, bytes]:
        nonlocal cache
        raw = manifest_file.read_bytes()
        etag = '"' + hashlib.sha256(raw).hexdigest() + '"'
        with cache_lock:
            if cache is None or cache[1] != etag:
                chunks = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
                if any(not isinstance(chunk, dict) for chunk in chunks):
                    raise ValueError('manifest records must be JSON objects')
                body = json.dumps({'chunks': chunks, 'total': len(chunks), 'offset': 0, 'limit': None}).encode('utf-8')
                cache = (chunks, etag, body)
            return cache

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            body = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parts = urllib_parse.urlsplit(self.path)
            if parts.path == '/healthz':
                self._send(200, {'status': 'ok'})
                return
            if parts.path == '/chunks':
                try:
                    chunks, etag, full_body = _load()
                except FileNotFoundError:
                    self._send(404, {'error': 'manifest missing'})
                    return
                except (OSError, ValueError, UnicodeError):
                    self._send(503, {'error': 'manifest unavailable; re-run aigit chunk'},
                               headers={'Retry-After': '1'})
                    return
                query = urllib_parse.parse_qs(parts.query)
                path_prefix = query.get('path', [None])[0]
                try:
                    offset = int(query.get('offset', ['0'])[0])
                    limit_raw = query.get('limit', [None])[0]
                    limit = int(limit_raw) if limit_raw is not None else None
                except ValueError:
                    self._send(400, {'error': 'offset and limit must be integers'})
                    return
                full_request = not path_prefix and offset <= 0 and limit is None
                if not full_request:
                    representation = json.dumps([etag, path_prefix, max(offset, 0), limit]).encode('utf-8')
                    etag = '"' + hashlib.sha256(representation).hexdigest() + '"'
                if self.headers.get('If-None-Match') == etag:
                    self.send_response(304)
                    self.send_header('ETag', etag)
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    return
                # Fast path: unfiltered full request serves precomputed bytes.
                if full_request:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(full_body)))
                    self.send_header('ETag', etag)
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    self.wfile.write(full_body)
                    return
                page, total = _filter_paginate(chunks, path_prefix, offset, limit)
                self._send(
                    200,
                    {'chunks': page, 'total': total, 'offset': max(offset, 0), 'limit': limit},
                    headers={'ETag': etag, 'Cache-Control': 'no-cache'},
                )
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
    chunk_args = argparse.Namespace(repo=str(repo_root), strict=True, check=False)
    chunk_rc = cmd_chunk(chunk_args)
    if chunk_rc != 0:
        print('ERROR: semantic rebuild failed (unparseable source under --strict)')
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
        'PYTHON_BIN="${PYTHON:-python3}"\n\n'
        'echo "[devx-quickcheck] starting"\n'
        '"${PYTHON_BIN}" -m aigit.cli chunk --repo .\n\n'
        'if command -v aigit >/dev/null 2>&1; then\n'
        '  AIGIT_BIN="aigit"\n'
        'else\n'
        '  AIGIT_BIN="${PYTHON_BIN} -m aigit.cli"\n'
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
        'if "${PYTHON_BIN}" - <<\'PY\'\n'
        'import importlib.util\n'
        'raise SystemExit(0 if importlib.util.find_spec("pytest") else 1)\n'
        'PY\n'
        'then\n'
        '  echo "[devx-quickcheck] running pytest"\n'
        '  "${PYTHON_BIN}" -m pytest --tb=short -q "${1:-tests}"\n'
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

    def _display(path: Path) -> str:
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            return path.as_posix()

    print('=== Subagent Scout ===')
    print(f'scanning repository: {repo_root.as_posix()}')
    summary = scout_repo(repo_root)
    report = _render_scout_report(summary)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report, encoding='utf-8')
    print(f'wrote scout report: {_display(output_file)}')
    if args.json_output:
        json_output = Path(args.json_output)
        if not json_output.is_absolute():
            json_output = repo_root / json_output
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(_scout_summary_json(summary), indent=2) + '\n', encoding='utf-8')
        print(f'wrote scout JSON: {_display(json_output)}')

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
    chunk.add_argument(
        '--strict',
        action='store_true',
        help='Exit non-zero if any source file cannot be parsed',
    )
    chunk.add_argument(
        '--check',
        action='store_true',
        help='Do not write; exit non-zero if committed artifacts are stale',
    )
    chunk.set_defaults(func=cmd_chunk)

    validate_ruleset = sub.add_parser('validate-ruleset', help='Validate the committed semantic ruleset')
    validate_ruleset.add_argument('--repo', default='.')
    validate_ruleset.set_defaults(func=cmd_validate_ruleset)

    eval_lineage = sub.add_parser('eval-lineage', help='Evaluate labeled lineage fixtures')
    eval_lineage.add_argument('--fixtures', required=True, help='Path to a version-1 lineage fixture JSON file')
    eval_lineage.add_argument('--output', help='Write the deterministic JSON report to this path')
    eval_lineage.add_argument('--min-precision', type=float, default=0.0)
    eval_lineage.add_argument('--min-recall', type=float, default=0.0)
    eval_lineage.set_defaults(func=cmd_eval_lineage)

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
    merge.add_argument(
        '--no-duplicate-work',
        action='store_true',
        help='Only report name-keyed conflicts; skip cross-name duplicate-work detection',
    )
    merge.set_defaults(func=cmd_merge)

    prov = sub.add_parser('record-provenance', help='Attach AI provenance to HEAD')
    prov.add_argument('--agent', required=True)
    prov.add_argument('--model', required=True)
    prov.add_argument('--prompt', required=True)
    prov.set_defaults(func=cmd_record_provenance)

    verify_prov = sub.add_parser('verify-provenance', help='Verify AI provenance for a commit')
    verify_prov.add_argument('--ref', default='HEAD')
    verify_prov.add_argument(
        '--require-signature',
        dest='require_signature',
        action='store_true',
        help='Fail unless the provenance log row carries a valid HMAC signature',
    )
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

    merge_driver = sub.add_parser(
        'merge-driver',
        help='Git merge driver for .semantic artifacts (invoked by Git as %%O %%A %%B %%P)',
    )
    merge_driver.add_argument('base')
    merge_driver.add_argument('ours')
    merge_driver.add_argument('theirs')
    merge_driver.add_argument('path', nargs='?', default='')
    merge_driver.set_defaults(func=cmd_merge_driver)

    install_merge_driver = sub.add_parser(
        'install-merge-driver',
        help='Merge .semantic artifacts by source file instead of by line in this clone',
    )
    install_merge_driver.add_argument('--repo', default='.')
    install_merge_driver.set_defaults(func=cmd_install_merge_driver)

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
