"""Tests for app/handlers.py — the minimal extraction landed during the
pre-delivery code review (D-1)."""
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.handlers as handlers


# ---------------------------------------------------------------------------
# reload_retriever — kills the 4× duplicated block previously in app.py
# ---------------------------------------------------------------------------

def test_reload_retriever_returns_retriever_on_success(monkeypatch):
    """Successful load returns (retriever, success_message)."""
    fake_retriever = mock.MagicMock()

    def fake_load_retriever(**kwargs):
        # Confirm the helper threaded sermon_root through correctly
        assert kwargs.get('sermon_root') == '/path/to/library'
        return fake_retriever

    fake_retriever_module = mock.MagicMock()
    fake_retriever_module.load_retriever = fake_load_retriever
    monkeypatch.setitem(sys.modules, 'app.retriever', fake_retriever_module)

    result, msg = handlers.reload_retriever('/path/to/library')
    assert result is fake_retriever
    assert 'reloaded successfully' in msg.lower()


def test_reload_retriever_returns_none_on_failure(monkeypatch):
    """Exception → (None, failure_message). No re-raise — caller decides."""
    def fake_load_retriever(**kwargs):
        raise RuntimeError("FAISS read failed")

    fake_retriever_module = mock.MagicMock()
    fake_retriever_module.load_retriever = fake_load_retriever
    monkeypatch.setitem(sys.modules, 'app.retriever', fake_retriever_module)

    result, msg = handlers.reload_retriever('/path/to/library')
    assert result is None
    assert 'failed' in msg.lower()
    assert 'FAISS' in msg  # exception detail flows into the technical log/string


def test_reload_retriever_passes_sermon_root(monkeypatch):
    """sermon_root threads through unchanged."""
    captured = {}

    def fake_load_retriever(**kwargs):
        captured.update(kwargs)
        return mock.MagicMock()

    fake_retriever_module = mock.MagicMock()
    fake_retriever_module.load_retriever = fake_load_retriever
    monkeypatch.setitem(sys.modules, 'app.retriever', fake_retriever_module)

    handlers.reload_retriever('/sermons/2024')
    assert captured['sermon_root'] == '/sermons/2024'
