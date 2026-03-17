from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


VENDOR_ROOT = Path(__file__).resolve().parent.parent / '.deerflow' / 'vendor' / 'deer-flow'


def _require_vendor_tree() -> Path:
    if not VENDOR_ROOT.exists():
        pytest.skip('optional DeerFlow vendor tree is not available in this checkout')
    return VENDOR_ROOT


def _load_runtime_context_module():
    module_path = (
        _require_vendor_tree()
        / 'backend'
        / 'packages'
        / 'harness'
        / 'deerflow'
        / 'utils'
        / 'runtime_context.py'
    )
    spec = spec_from_file_location('deerflow_vendor_runtime_context', module_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RuntimeStub:
    def __init__(self, *, context=None, config=None):
        self.context = context
        self.config = config if config is not None else {}


def test_vendor_runtime_thread_id_prefers_context():
    runtime_context = _load_runtime_context_module()
    runtime = _RuntimeStub(
        context={'thread_id': 'context-thread'},
        config={'configurable': {'thread_id': 'config-thread'}},
    )

    assert runtime_context.get_runtime_thread_id(runtime) == 'context-thread'


def test_vendor_runtime_thread_id_falls_back_to_configurable():
    runtime_context = _load_runtime_context_module()
    runtime = _RuntimeStub(
        context=None,
        config={'configurable': {'thread_id': 'config-thread'}},
    )

    assert runtime_context.get_runtime_thread_id(runtime) == 'config-thread'


def test_vendor_runtime_context_setter_initializes_missing_context():
    runtime_context = _load_runtime_context_module()
    runtime = _RuntimeStub(context=None)

    runtime_context.set_runtime_context_value(runtime, 'sandbox_id', 'sandbox-123')

    assert runtime.context == {'sandbox_id': 'sandbox-123'}


def test_vendor_langgraph_dev_compose_disables_reload():
    compose_file = (
        _require_vendor_tree()
        / 'docker'
        / 'docker-compose-dev.yaml'
    )

    assert '--no-reload' in compose_file.read_text(encoding='utf-8')


def test_vendor_paths_define_direct_repo_workspace_contract(tmp_path: Path):
    module_path = (
        _require_vendor_tree()
        / 'backend'
        / 'packages'
        / 'harness'
        / 'deerflow'
        / 'config'
        / 'paths.py'
    )
    spec = spec_from_file_location('deerflow_vendor_paths', module_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    paths = module.Paths(base_dir=tmp_path)

    assert module.sandbox_repo_virtual_path() == '/mnt/user-data/workspace/repo'
    assert paths.sandbox_repo_dir('thread_123').as_posix().endswith('/threads/thread_123/user-data/workspace/repo')
