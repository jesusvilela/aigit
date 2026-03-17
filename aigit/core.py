from __future__ import annotations

import argparse
import ast
import dataclasses
import difflib
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SEMANTIC_DIR = Path('.semantic')
MANIFEST_FILE = SEMANTIC_DIR / 'manifest.jsonl'
EDGES_FILE = SEMANTIC_DIR / 'edges.jsonl'
INDEX_FILE = SEMANTIC_DIR / 'chunk_index.json'
RULESET_FILE = SEMANTIC_DIR / 'ruleset.yaml'
SCHEMA_FILE = SEMANTIC_DIR / 'schema_version'

DEERFLOW_VENDOR_DIR = Path('.deerflow/vendor/deer-flow')
DEERFLOW_LAUNCH_SCRIPT = Path('scripts/run_deerflow.sh')
DEERFLOW_ENV_FILE = Path('.deerflow/.env.example')
DEERFLOW_CONFIG_FILE = Path('.deerflow/config.yaml')

ALLOWED_PARSER_BACKENDS = {'python-ast', 'markdown-headings', 'file'}


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


def parse_file(full_path: Path, rel_path: str) -> list[Chunk]:
    text = full_path.read_text(encoding='utf-8', errors='replace')
    suffix = full_path.suffix.lower()
    if suffix == '.py':
        return parse_python(rel_path, text)
    if suffix in {'.md', '.markdown'}:
        return parse_markdown(rel_path, text)
    return parse_text(rel_path, text)


def load_previous_index() -> dict[str, dict[str, Any]]:
    if not INDEX_FILE.exists():
        return {}
    return json.loads(INDEX_FILE.read_text(encoding='utf-8'))


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
        if any(part.startswith('.') and part != '.github' for part in rel.parts):
            continue
        files.append(rel)
    return sorted(files)




def _parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' '):
            if ':' not in line:
                raise ValueError(f"invalid ruleset line: {raw_line}")
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            if not value:
                data[key] = {}
                current_section = key
            else:
                data[key] = value
                current_section = None
            continue
        if current_section is None:
            raise ValueError(f"nested ruleset entry without section: {raw_line}")
        entry = line.strip()
        if ':' not in entry:
            raise ValueError(f"invalid nested ruleset line: {raw_line}")
        key, value = entry.split(':', 1)
        data[current_section][key.strip()] = value.strip()
    return data


def _parse_bool(value: str) -> bool:
    lowered = value.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    raise ValueError(f'invalid boolean value: {value}')


def validate_ruleset_content(text: str) -> dict[str, Any]:
    ruleset = _parse_simple_yaml(text)
    if 'version' not in ruleset:
        raise ValueError('ruleset missing version')
    try:
        version = int(str(ruleset['version']))
    except ValueError as exc:
        raise ValueError('ruleset version must be an integer') from exc
    if version < 1:
        raise ValueError('ruleset version must be >= 1')

    parsers = ruleset.get('parsers')
    if not isinstance(parsers, dict) or not parsers:
        raise ValueError('ruleset.parsers must be a non-empty map')
    if 'default' not in parsers:
        raise ValueError('ruleset.parsers must include default')
    for ext, backend in parsers.items():
        if ext != 'default' and not ext.startswith('.'):
            raise ValueError(f'parser key must start with .: {ext}')
        if backend not in ALLOWED_PARSER_BACKENDS:
            raise ValueError(f'unsupported parser backend: {backend}')

    identity = ruleset.get('identity', {})
    if isinstance(identity, dict) and 'false_positive_policy' in identity:
        if identity['false_positive_policy'] not in {'prefer-new-node'}:
            raise ValueError('identity.false_positive_policy must be prefer-new-node')

    canonicalization = ruleset.get('canonicalization', {})
    if isinstance(canonicalization, dict):
        if 'line_endings' in canonicalization and canonicalization['line_endings'] not in {'lf', 'crlf'}:
            raise ValueError('canonicalization.line_endings must be lf or crlf')
        if 'trim_trailing_whitespace' in canonicalization:
            _parse_bool(canonicalization['trim_trailing_whitespace'])

    return ruleset


def validate_ruleset_file(path: Path = RULESET_FILE) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f'ruleset file missing: {path}')
    return validate_ruleset_content(path.read_text(encoding='utf-8'))

def ensure_semantic_scaffold() -> None:
    SEMANTIC_DIR.mkdir(exist_ok=True)
    (SEMANTIC_DIR / 'cache').mkdir(exist_ok=True)
    if not SCHEMA_FILE.exists():
        SCHEMA_FILE.write_text('1\n', encoding='utf-8')
    if not RULESET_FILE.exists():
        RULESET_FILE.write_text(
            'version: 1\nparsers:\n  .py: python-ast\n  .md: markdown-headings\n  default: file\n',
            encoding='utf-8',
        )


def build_manifest(root: Path) -> tuple[list[Chunk], list[dict[str, Any]]]:
    ensure_semantic_scaffold()
    previous = load_previous_index()
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


def write_manifest(chunks: list[Chunk], edges: list[dict[str, Any]]) -> None:
    manifest_lines = [json.dumps(chunk.to_dict(), sort_keys=True) for chunk in chunks]
    MANIFEST_FILE.write_text('\n'.join(manifest_lines) + ('\n' if manifest_lines else ''), encoding='utf-8')
    edge_lines = [json.dumps(edge, sort_keys=True) for edge in edges]
    EDGES_FILE.write_text('\n'.join(edge_lines) + ('\n' if edge_lines else ''), encoding='utf-8')
    index: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        key = f"{chunk.path}::{chunk.chunk_type}::{chunk.anchor}"
        index[key] = chunk.to_dict()
    INDEX_FILE.write_text(json.dumps(index, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def cmd_chunk(args: argparse.Namespace) -> int:
    if not args.no_validate:
        validate_ruleset_file()
    chunks, edges = build_manifest(Path(args.repo).resolve())
    write_manifest(chunks, edges)
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




def cmd_validate_ruleset(_: argparse.Namespace) -> int:
    ruleset = validate_ruleset_file()
    print(f"ruleset valid (version={ruleset['version']})")
    return 0

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
        if (
            o['content_hash'] != b['content_hash']
            and t['content_hash'] != b['content_hash']
            and o['content_hash'] != t['content_hash']
        ):
            conflicts.append(sid)
    out = {'base': args.base, 'ours': args.ours, 'theirs': args.theirs, 'conflicts': conflicts}
    Path(args.output).write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print(f'detected {len(conflicts)} semantic conflicts')
    return 0


def cmd_record_provenance(args: argparse.Namespace) -> int:
    ensure_semantic_scaffold()
    commit = _run_git(['rev-parse', 'HEAD'])
    row = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'commit': commit,
        'agent': args.agent,
        'model': args.model,
        'prompt_hash': _hash([args.prompt]),
    }
    path = SEMANTIC_DIR / 'provenance.jsonl'
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, sort_keys=True) + '\n')
    print(f'appended provenance to {path}')
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


def bootstrap_deerflow_files() -> None:
    _write_file_if_missing(
        DEERFLOW_ENV_FILE,
        '# Copy this file to .deerflow/.env and fill secrets\n'
        'OPENAI_API_KEY=\n'
        'TAVILY_API_KEY=\n'
        'INFOQUEST_API_KEY=\n',
    )
    _write_file_if_missing(
        DEERFLOW_CONFIG_FILE,
        'models:\n'
        '  - name: gpt-4o-mini\n'
        '    display_name: GPT-4o Mini\n'
        '    use: langchain_openai:ChatOpenAI\n'
        '    model: gpt-4o-mini\n'
        '    api_key: $OPENAI_API_KEY\n'
        '    max_tokens: 4096\n'
        '    temperature: 0.2\n'
        '\n'
        'sandbox:\n'
        '  use: deerflow.community.docker_sandbox:DockerSandboxProvider\n'
        '\n'
        'channels:\n'
        '  session:\n'
        '    assistant_id: lead_agent\n'
        '    config:\n'
        '      recursion_limit: 120\n'
        '    context:\n'
        '      thinking_enabled: true\n'
        '      is_plan_mode: true\n'
        '      subagent_enabled: true\n',
    )
    _write_file_if_missing(
        DEERFLOW_LAUNCH_SCRIPT,
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        'DEERFLOW_DIR="$REPO_ROOT/.deerflow/vendor/deer-flow"\n'
        'if [ ! -d "$DEERFLOW_DIR" ]; then\n'
        '  echo "deer-flow vendor directory missing. Run: aigit init-deerflow" >&2\n'
        '  exit 1\n'
        'fi\n'
        'cd "$DEERFLOW_DIR"\n'
        'make docker-init\n'
        'make docker-start\n',
    )
    DEERFLOW_LAUNCH_SCRIPT.chmod(0o755)


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
        subprocess.run(['git', '-C', str(DEERFLOW_VENDOR_DIR), 'pull', '--ff-only'], check=True)

    subprocess.run(['make', 'config'], cwd=DEERFLOW_VENDOR_DIR, check=True)
    print(f'initialized deer-flow harness in {DEERFLOW_VENDOR_DIR}')
    print('next: copy .deerflow/.env.example to .deerflow/.env and set API keys')
    return 0


def serve_api(args: argparse.Namespace) -> int:
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
                if not MANIFEST_FILE.exists():
                    self._send(404, {'error': 'manifest missing'})
                    return
                chunks = [json.loads(line) for line in MANIFEST_FILE.read_text(encoding='utf-8').splitlines() if line]
                self._send(200, {'chunks': chunks})
                return
            self._send(404, {'error': 'not found'})

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'serving API on http://{args.host}:{args.port}')
    server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='aigit')
    sub = parser.add_subparsers(dest='command', required=True)

    chunk = sub.add_parser('chunk', help='Generate deterministic semantic manifest')
    chunk.add_argument('--repo', default='.')
    chunk.add_argument('--no-validate', action='store_true', help='Skip ruleset preflight validation')
    chunk.set_defaults(func=cmd_chunk)

    validate = sub.add_parser('validate-ruleset', help='Validate .semantic/ruleset.yaml for deterministic chunking')
    validate.set_defaults(func=cmd_validate_ruleset)

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

    api = sub.add_parser('serve-api', help='Serve local chunk API')
    api.add_argument('--host', default='127.0.0.1')
    api.add_argument('--port', type=int, default=8765)
    api.set_defaults(func=serve_api)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
