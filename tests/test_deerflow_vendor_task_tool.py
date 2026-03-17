from pathlib import Path


def test_vendor_task_tool_keeps_subagent_config_separate_from_runtime_config():
    task_tool_path = (
        Path(__file__).resolve().parent.parent
        / '.deerflow'
        / 'vendor'
        / 'deer-flow'
        / 'backend'
        / 'packages'
        / 'harness'
        / 'deerflow'
        / 'tools'
        / 'builtins'
        / 'task_tool.py'
    )

    source = task_tool_path.read_text(encoding='utf-8')
    lines = source.splitlines()

    assert 'subagent_config = get_subagent_config(subagent_type)' in source
    assert 'runtime_config = getattr(runtime, "config", {}) or {}' in source
    assert 'config=subagent_config' in source
    assert '        config = getattr(runtime, "config", {}) or {}' not in lines
