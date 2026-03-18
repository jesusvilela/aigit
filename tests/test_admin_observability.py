import json
from pathlib import Path

from aigit import core


def test_collect_semantic_summary(tmp_path: Path) -> None:
    semantic_dir = tmp_path / '.semantic'
    semantic_dir.mkdir()
    (semantic_dir / 'manifest.jsonl').write_text(
        json.dumps({'chunk_type': 'function'}) + '\n' + json.dumps({'chunk_type': 'section'}) + '\n',
        encoding='utf-8',
    )
    (semantic_dir / 'edges.jsonl').write_text(json.dumps({'from': 'a', 'to': 'b'}) + '\n', encoding='utf-8')
    (semantic_dir / 'provenance.jsonl').write_text(json.dumps({'commit': 'abc'}) + '\n', encoding='utf-8')
    (semantic_dir / 'schema_version').write_text('1\n', encoding='utf-8')
    (semantic_dir / 'ruleset.yaml').write_text('version: 1\n', encoding='utf-8')

    summary = core.collect_semantic_summary(tmp_path)

    assert summary['manifest_exists'] is True
    assert summary['chunk_count'] == 2
    assert summary['edge_count'] == 1
    assert summary['provenance_count'] == 1
    assert summary['schema_version'] == '1'
    assert summary['chunk_types'] == [
        {'chunk_type': 'function', 'count': 1},
        {'chunk_type': 'section', 'count': 1},
    ]


def test_collect_epic_queue_status(tmp_path: Path) -> None:
    deerflow_dir = tmp_path / '.deerflow'
    objectives_dir = deerflow_dir / 'objectives'
    docs_dir = tmp_path / 'docs' / 'epics'
    objectives_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)
    (objectives_dir / 'ALL_EPICS.md').write_text('# all\n', encoding='utf-8')
    (objectives_dir / 'EPIC-01.md').write_text('# one\n', encoding='utf-8')
    (docs_dir / 'EPIC-01-demo.md').write_text('# source\n', encoding='utf-8')
    (deerflow_dir / 'epic_queue.json').write_text(
        json.dumps(
            [
                {
                    'id': 'EPIC-01',
                    'title': 'EPIC-01: Demo',
                    'objective_file': '.deerflow/objectives/EPIC-01.md',
                    'source_file': 'docs/epics/EPIC-01-demo.md',
                }
            ]
        )
        + '\n',
        encoding='utf-8',
    )

    queue = core.collect_epic_queue_status(tmp_path)

    assert queue['queue_exists'] is True
    assert queue['master_exists'] is True
    assert queue['objective_count'] == 1
    assert queue['entries'][0]['objective_exists'] is True
    assert queue['entries'][0]['source_exists'] is True


def test_get_deerflow_thread_details(tmp_path: Path, monkeypatch) -> None:
    threads_root = tmp_path / 'threads'
    repo_workspace = threads_root / 'thread-123' / 'user-data' / 'workspace' / 'repo'
    repo_workspace.mkdir(parents=True)
    (repo_workspace / 'sample.py').write_text('print("ok")\n', encoding='utf-8')
    metadata_file = threads_root / 'thread-123' / 'user-data' / 'workspace' / core.DEERFLOW_SYNC_METADATA
    metadata_file.write_text(
        json.dumps({'sandbox_workspace': '/mnt/user-data/workspace/repo', 'workspace_subdir': 'repo'}) + '\n',
        encoding='utf-8',
    )

    monkeypatch.setattr(core, 'deerflow_threads_dir', lambda: threads_root)

    details = core.get_deerflow_thread_details('thread-123')

    assert details is not None
    assert details['thread_id'] == 'thread-123'
    assert details['repo_workspace_files'] == 1
    assert details['metadata_present'] is True