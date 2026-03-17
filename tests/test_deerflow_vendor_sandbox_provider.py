from pathlib import Path


def test_vendor_sandbox_provider_uses_a_lock_for_singleton_initialization():
    provider_path = (
        Path(__file__).resolve().parent.parent
        / '.deerflow'
        / 'vendor'
        / 'deer-flow'
        / 'backend'
        / 'packages'
        / 'harness'
        / 'deerflow'
        / 'sandbox'
        / 'sandbox_provider.py'
    )

    source = provider_path.read_text(encoding='utf-8')

    assert 'import threading' in source
    assert '_default_sandbox_provider_lock = threading.Lock()' in source
    assert 'with _default_sandbox_provider_lock:' in source
