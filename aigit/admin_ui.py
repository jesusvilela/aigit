from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from aigit.core import collect_admin_snapshot, get_deerflow_container_logs, get_deerflow_thread_details


def _format_bool(flag: bool) -> str:
    return 'Yes' if flag else 'No'


def _overview_html(snapshot: dict[str, Any]) -> str:
    deerflow = snapshot['deerflow']
    semantic = snapshot['semantic']
    git = snapshot['git']
    api_ok = sum(1 for item in deerflow['api_health'] if item['ok'])
    cards = [
        ('Git Branch', git['branch'] or 'n/a', 'Tracks the active repository context.'),
        ('Dirty Files', str(git['changed_count']), 'Uncommitted changes in the working tree.'),
        ('Queue Objectives', str(deerflow['objective_count']), 'Prepared DeerFlow roadmap objectives.'),
        ('Threads', str(deerflow['thread_count']), 'Discovered DeerFlow thread workspaces.'),
        ('Semantic Chunks', str(semantic['chunk_count']), 'Current manifest chunk count.'),
        ('API Checks', f'{api_ok}/{len(deerflow["api_health"])}', 'Reachable DeerFlow API health probes.'),
    ]
    card_html = ''.join(
        f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div><div class='metric-note'>{note}</div></div>"
        for label, value, note in cards
    )
    return f"""
    <div class='admin-shell'>
      <div class='hero-panel'>
        <div>
          <div class='eyebrow'>AIGit Admin</div>
          <h1>Agentic Harness Observatory</h1>
          <p>Local control plane for the DeerFlow roadmap, semantic storage, and staged thread workspaces.</p>
        </div>
        <div class='repo-chip'>{snapshot['repo_root']}</div>
      </div>
      <div class='metric-grid'>{card_html}</div>
    </div>
    """


def _git_markdown(snapshot: dict[str, Any]) -> str:
    git = snapshot['git']
    changed = '\n'.join(f'- {line}' for line in git['changed_files']) or '- clean'
    return (
        '### Git State\n'
        f"- Branch: {git['branch'] or 'n/a'}\n"
        f"- Dirty: {_format_bool(git['dirty'])}\n"
        f"- Changed entries: {git['changed_count']}\n"
        f"- Snapshot generated: {snapshot['generated_at']}\n\n"
        f'{changed}'
    )


def _queue_rows(snapshot: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for entry in snapshot['epics']['entries']:
        rows.append(
            [
                entry['id'],
                entry['title'],
                _format_bool(entry['objective_exists']),
                _format_bool(entry['source_exists']),
                entry['objective_file'],
            ]
        )
    return rows


def _semantic_markdown(snapshot: dict[str, Any]) -> str:
    semantic = snapshot['semantic']
    return (
        '### Semantic Storage\n'
        f"- Manifest present: {_format_bool(semantic['manifest_exists'])}\n"
        f"- Chunk count: {semantic['chunk_count']}\n"
        f"- Edge count: {semantic['edge_count']}\n"
        f"- Provenance rows: {semantic['provenance_count']}\n"
        f"- Schema version: {semantic['schema_version'] or 'n/a'}\n"
        f"- Ruleset present: {_format_bool(semantic['ruleset_present'])}\n"
        f"- Last manifest update: {semantic['last_updated'] or 'n/a'}"
    )


def _semantic_rows(snapshot: dict[str, Any]) -> list[list[Any]]:
    return [[row['chunk_type'], row['count']] for row in snapshot['semantic']['chunk_types']]


def _thread_rows(snapshot: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for thread in snapshot['threads']:
        rows.append(
            [
                thread['thread_id'],
                thread['repo_workspace_files'],
                thread['output_files'],
                thread['upload_files'],
                _format_bool(thread['metadata_present']),
                thread['last_updated'] or 'n/a',
            ]
        )
    return rows


def _containers_rows(snapshot: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for container in snapshot['deerflow']['containers']:
        rows.append([container['name'], container['image'], container['status'], container['ports']])
    return rows


def _runtime_markdown(snapshot: dict[str, Any]) -> str:
    deerflow = snapshot['deerflow']
    api_lines = '\n'.join(
        f"- {item['name']}: {'ok' if item['ok'] else 'down'}" + (f" ({item['status']})" if item['status'] else '') + f" — {item['detail']}"
        for item in deerflow['api_health']
    )
    key_lines = '\n'.join(f'- {key}: {_format_bool(value)}' for key, value in deerflow['configured_keys'].items())
    return (
        '### Harness Runtime\n'
        f"- Vendored harness present: {_format_bool(deerflow['vendor_exists'])}\n"
        f"- Local config present: {_format_bool(deerflow['config_present'])}\n"
        f"- Local runtime env present: {_format_bool(deerflow['runtime_env_present'])}\n"
        f"- Launch script present: {_format_bool(deerflow['launch_script_present'])}\n"
        f"- Recovery script present: {_format_bool(deerflow['recovery_script_present'])}\n\n"
        'Configured keys:\n'
        f'{key_lines}\n\n'
        'API health:\n'
        f'{api_lines}'
    )


def _thread_details_markdown(snapshot: dict[str, Any], thread_id: str) -> str:
    target = thread_id.strip()
    if not target:
        return 'Enter a thread id to inspect its staged workspace and sync metadata.'
    thread = get_deerflow_thread_details(target)
    if thread is None:
        return f'No DeerFlow thread found for `{target}`.'
    metadata = thread['metadata']
    metadata_lines = '\n'.join(f'- {key}: {value}' for key, value in sorted(metadata.items())) or '- none'
    return (
        f"### Thread {thread['thread_id']}\n"
        f"- Thread path: {thread['thread_path']}\n"
        f"- Workspace path: {thread['workspace_path']}\n"
        f"- Repo workspace path: {thread['repo_workspace_path']}\n"
        f"- Sandbox workspace: {thread['sandbox_workspace']}\n"
        f"- Repo workspace files: {thread['repo_workspace_files']}\n"
        f"- Output files: {thread['output_files']}\n"
        f"- Upload files: {thread['upload_files']}\n"
        f"- Sync metadata present: {_format_bool(thread['metadata_present'])}\n"
        f"- Last updated: {thread['last_updated'] or 'n/a'}\n\n"
        'Metadata:\n'
        f'{metadata_lines}'
    )


def _run_action(repo_root: Path, command: list[str]) -> str:
    proc = subprocess.run(command, cwd=repo_root, text=True, capture_output=True)
    output = proc.stdout.strip()
    error = proc.stderr.strip()
    combined = '\n'.join(part for part in (output, error) if part)
    status = 'success' if proc.returncode == 0 else f'failed ({proc.returncode})'
    rendered_command = ' '.join(command)
    return f'$ {rendered_command}\n[{status}]\n{combined or "no output"}'


def _refresh_dashboard(repo_root: Path) -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str]:
    snapshot = collect_admin_snapshot(repo_root)
    return (
        _overview_html(snapshot),
        _git_markdown(snapshot),
        _queue_rows(snapshot),
        _semantic_markdown(snapshot),
        _semantic_rows(snapshot),
        _runtime_markdown(snapshot),
        _thread_rows(snapshot),
        _containers_rows(snapshot),
        f"Last refresh: {snapshot['generated_at']}",
    )


def _run_and_refresh(repo_root: Path, command: list[str]) -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str, str]:
    action_output = _run_action(repo_root, command)
    refreshed = _refresh_dashboard(repo_root)
    return (*refreshed, action_output)


def launch_admin_ui(repo_root: Path, host: str, port: int, share: bool = False) -> None:
    try:
        import gradio as gr
    except ImportError as exc:  # pragma: no cover - runtime dependency error path
        raise ImportError('gradio is not installed') from exc

    repo_root = repo_root.resolve()

    css = """
    :root {
      --panel: linear-gradient(180deg, #f5efe4 0%, #fbf7ef 100%);
      --ink: #1d2a24;
      --muted: #5a6a62;
      --accent: #0f766e;
      --accent-soft: #d9efe8;
      --line: rgba(29, 42, 36, 0.12);
    }
    .gradio-container { background: radial-gradient(circle at top left, #f4ead1 0%, #f6f1e6 38%, #edf3ef 100%); }
    .admin-shell { display: grid; gap: 1rem; }
    .hero-panel {
      display: flex; justify-content: space-between; align-items: end; gap: 1rem;
      background: var(--panel); border: 1px solid var(--line); border-radius: 22px; padding: 1.2rem 1.4rem;
      box-shadow: 0 18px 40px rgba(31, 41, 35, 0.08);
    }
    .hero-panel h1 { margin: 0; color: var(--ink); font-size: 2rem; }
    .hero-panel p, .metric-note, .eyebrow { color: var(--muted); }
    .eyebrow { text-transform: uppercase; letter-spacing: 0.14em; font-size: 0.74rem; margin-bottom: 0.4rem; }
    .repo-chip {
      background: #fffdf7; border: 1px solid var(--line); border-radius: 999px; padding: 0.55rem 0.9rem;
      color: var(--ink); font-family: monospace; font-size: 0.9rem;
    }
    .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.9rem; }
    .metric-card {
      background: rgba(255,255,255,0.72); border: 1px solid var(--line); border-radius: 18px; padding: 0.95rem;
      backdrop-filter: blur(8px);
    }
    .metric-label { color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; }
    .metric-value { color: var(--ink); font-size: 1.7rem; font-weight: 700; margin: 0.25rem 0; }
    """

    with gr.Blocks(title='AIGit Admin Observatory', css=css, theme=gr.themes.Soft(primary_hue='teal', neutral_hue='stone')) as demo:
        gr.HTML(_overview_html(collect_admin_snapshot(repo_root)))

        with gr.Row():
            refresh_button = gr.Button('Refresh Observatory', variant='primary')
            prepare_button = gr.Button('Prepare Epic Bundle')
            launch_button = gr.Button('Start Harness')
            recover_button = gr.Button('Recover Harness')
            rechunk_button = gr.Button('Rebuild Semantic Manifest')

        action_output = gr.Textbox(label='Operator Output', lines=8, interactive=False)

        with gr.Tab('Overview'):
            git_md = gr.Markdown()
            runtime_md = gr.Markdown()

        with gr.Tab('Epic Queue'):
            queue_df = gr.Dataframe(
                headers=['Epic', 'Title', 'Objective File', 'Source File', 'Objective Path'],
                datatype=['str', 'str', 'str', 'str', 'str'],
                interactive=False,
                row_count=(0, 'dynamic'),
                col_count=(5, 'fixed'),
                wrap=True,
                label='Prepared roadmap objectives',
            )

        with gr.Tab('Semantic'):
            semantic_md = gr.Markdown()
            semantic_df = gr.Dataframe(
                headers=['Chunk Type', 'Count'],
                datatype=['str', 'number'],
                interactive=False,
                row_count=(0, 'dynamic'),
                col_count=(2, 'fixed'),
                label='Chunk distribution',
            )

        with gr.Tab('Threads'):
            threads_df = gr.Dataframe(
                headers=['Thread ID', 'Repo Files', 'Outputs', 'Uploads', 'Synced', 'Last Updated'],
                datatype=['str', 'number', 'number', 'number', 'str', 'str'],
                interactive=False,
                row_count=(0, 'dynamic'),
                col_count=(6, 'fixed'),
                label='Known DeerFlow threads',
            )
            with gr.Row():
                thread_id = gr.Textbox(label='Inspect Thread ID', placeholder='epic-01-launch-20260317a')
                inspect_thread = gr.Button('Inspect Thread')
            thread_details = gr.Markdown('Enter a thread id to inspect its staged workspace and sync metadata.')

        with gr.Tab('Containers'):
            containers_df = gr.Dataframe(
                headers=['Name', 'Image', 'Status', 'Ports'],
                datatype=['str', 'str', 'str', 'str'],
                interactive=False,
                row_count=(0, 'dynamic'),
                col_count=(4, 'fixed'),
                label='DeerFlow-related containers',
            )
            with gr.Row():
                container_name = gr.Textbox(label='Container Name', placeholder='deer-flow-nginx')
                tail_lines = gr.Slider(label='Tail Lines', minimum=20, maximum=400, step=20, value=120)
                load_logs = gr.Button('Load Container Logs')
            container_logs = gr.Textbox(label='Container Logs', lines=18, interactive=False)

        footer = gr.Markdown()

        refresh_outputs = [
            demo.children[0],
            git_md,
            queue_df,
            semantic_md,
            semantic_df,
            runtime_md,
            threads_df,
            containers_df,
            footer,
        ]

        def refresh_state() -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str]:
            return _refresh_dashboard(repo_root)

        def prepare_state() -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str, str]:
            return _run_and_refresh(repo_root, [sys.executable, '-m', 'aigit.cli', 'launch-epics', '--bootstrap-deerflow'])

        def launch_state() -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str, str]:
            return _run_and_refresh(
                repo_root,
                [sys.executable, '-m', 'aigit.cli', 'launch-epics', '--bootstrap-deerflow', '--start-harness'],
            )

        def recover_state() -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str, str]:
            return _run_and_refresh(repo_root, [str((repo_root / 'scripts' / 'recover_deerflow.sh').resolve())])

        def rechunk_state() -> tuple[str, str, list[list[Any]], str, list[list[Any]], str, list[list[Any]], list[list[Any]], str, str]:
            return _run_and_refresh(repo_root, [sys.executable, '-m', 'aigit.cli', 'chunk', '--repo', str(repo_root)])

        refresh_button.click(refresh_state, outputs=refresh_outputs)
        demo.load(refresh_state, outputs=refresh_outputs)
        prepare_button.click(prepare_state, outputs=[*refresh_outputs, action_output])
        launch_button.click(launch_state, outputs=[*refresh_outputs, action_output])
        recover_button.click(recover_state, outputs=[*refresh_outputs, action_output])
        rechunk_button.click(rechunk_state, outputs=[*refresh_outputs, action_output])
        inspect_thread.click(lambda value: _thread_details_markdown(collect_admin_snapshot(repo_root), value), inputs=thread_id, outputs=thread_details)
        load_logs.click(lambda name, lines: get_deerflow_container_logs(name, int(lines)), inputs=[container_name, tail_lines], outputs=container_logs)

    demo.launch(server_name=host, server_port=port, share=share, inbrowser=False)