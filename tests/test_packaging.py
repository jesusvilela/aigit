"""Packaging/decoupling tests: the core must not require the UI extra."""
import argparse
import sys

from aigit import core


def test_core_import_does_not_pull_gradio():
    # Importing the semantic core must never drag in the heavy UI dependency.
    assert 'gradio' not in sys.modules


def test_admin_ui_without_gradio_is_friendly(monkeypatch, capsys):
    # Simulate gradio being absent: importing it raises ImportError.
    monkeypatch.setitem(sys.modules, 'gradio', None)
    args = argparse.Namespace(repo='.', host='127.0.0.1', port=7860, share=False)
    rc = core.cmd_admin_ui(args)
    assert rc == 1
    combined = capsys.readouterr()
    assert 'aigit[ui]' in (combined.out + combined.err)
