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


# ---------------------------------------------------------------------------
# _capture_run — generic stdout/stderr capture wrapper
# ---------------------------------------------------------------------------

def test_capture_run_collects_stdout_and_stderr():
    def task():
        print("on stdout")
        print("on stderr", file=sys.stderr)
        return 0
    out = handlers._capture_run(task, "test")
    assert "on stdout" in out
    assert "on stderr" in out
    # Successful run does NOT append an exit-code marker
    assert "[exit code:" not in out


def test_capture_run_appends_exit_code_on_nonzero_return():
    def task():
        print("partial output")
        return 7
    out = handlers._capture_run(task, "test")
    assert "partial output" in out
    assert "[exit code: 7]" in out


def test_capture_run_appends_traceback_on_exception():
    def task():
        print("before crash")
        raise RuntimeError("boom from task")
    out = handlers._capture_run(task, "test")
    assert "before crash" in out
    assert "[stderr]" in out
    assert "RuntimeError" in out and "boom from task" in out
    assert "[exit code: 1]" in out


def test_capture_run_forwards_logging_records():
    """logging.info() during the task should appear in the captured buffer."""
    def task():
        logging.getLogger("test_capture").info("hello via logging")
        return 0
    out = handlers._capture_run(task, "test")
    assert "hello via logging" in out


# ---------------------------------------------------------------------------
# run_ingest / run_embed — verify they build the right Namespace and capture
# ---------------------------------------------------------------------------

def test_run_ingest_calls_build_run_with_expected_args(monkeypatch):
    captured = {}
    def fake_run(args):
        captured['args'] = args
        print("ingest stdout")
        return 0
    fake_module = mock.MagicMock()
    fake_module.run = fake_run
    fake_module.PROCESSED_REGISTRY = '/fake/registry.json'
    monkeypatch.setitem(sys.modules, 'build.ingest_files', fake_module)
    fake_build_pkg = mock.MagicMock()
    fake_build_pkg.ingest_files = fake_module
    monkeypatch.setitem(sys.modules, 'build', fake_build_pkg)

    out = handlers.run_ingest(source='/sermons', force=True, verbose=True)

    assert "ingest stdout" in out
    ns = captured['args']
    assert ns.source == '/sermons'
    assert ns.force is True
    assert ns.verbose is True
    assert ns.no_progress is True  # captured stdout — must suppress tqdm
    assert ns.dry_run is False


def test_run_embed_calls_build_run_with_expected_args(monkeypatch):
    captured = {}
    def fake_run(args):
        captured['args'] = args
        return 0
    fake_module = mock.MagicMock()
    fake_module.run = fake_run
    monkeypatch.setitem(sys.modules, 'build.chunk_embed', fake_module)
    fake_build_pkg = mock.MagicMock()
    fake_build_pkg.chunk_embed = fake_module
    monkeypatch.setitem(sys.modules, 'build', fake_build_pkg)

    handlers.run_embed(incremental=True)

    ns = captured['args']
    assert ns.incremental is True
    assert ns.force is False
    assert ns.no_progress is True


def test_run_ingest_captures_exception_as_exit_code_1(monkeypatch):
    def fake_run(args):
        raise RuntimeError("ingest exploded")
    fake_module = mock.MagicMock()
    fake_module.run = fake_run
    fake_module.PROCESSED_REGISTRY = '/fake/registry.json'
    monkeypatch.setitem(sys.modules, 'build.ingest_files', fake_module)
    fake_build_pkg = mock.MagicMock()
    fake_build_pkg.ingest_files = fake_module
    monkeypatch.setitem(sys.modules, 'build', fake_build_pkg)

    out = handlers.run_ingest(source='/sermons')
    assert "ingest exploded" in out
    assert "[exit code: 1]" in out
