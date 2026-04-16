"""Tests for app/app.py — handle_query, on_row_select, and archive handlers.

All tests use mocks so no FAISS/SQLite/LLM artifacts are required.
"""
import sys
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.app as app_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks(n: int = 3, score: float = 0.025) -> list[dict]:
    """Build a list of fake chunk dicts for testing."""
    return [
        {
            'chunk_id':     f'doc_{i}::0',
            'doc_id':       f'doc_{i}',
            'title':        f'Sermon {i}',
            'scripture_ref': f'John {i}:1',
            'date':         f'2024-0{i+1}-01',
            'source_file':  f'SampleData/Sermon {i}.docx',
            'text':         'Grace and faith are central themes of the gospel. ' * 10,
            'score':        score,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# handle_query
# ---------------------------------------------------------------------------

def test_handle_query_empty_string():
    answer, rows, status, state = app_module.handle_query("", 5)
    assert rows == []
    assert state == []


def test_handle_query_whitespace_only():
    answer, rows, status, state = app_module.handle_query("   ", 5)
    assert rows == []


def test_handle_query_no_retriever():
    app_module._retriever = None
    answer, rows, status, state = app_module.handle_query("grace", 5)
    assert "not available" in answer.lower() or "retriever" in answer.lower()


def test_handle_query_returns_rows():
    chunks = _make_chunks(3)
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks

    app_module._retriever = mock_retriever
    app_module._llm = None  # LLM not loaded → fallback answer

    answer, rows, status, state = app_module.handle_query("grace", 5)

    assert len(rows) == 3
    assert state == chunks
    mock_retriever.search.assert_called_once_with("grace", top_k=5)


def test_handle_query_passes_top_k():
    chunks = _make_chunks(10)
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks

    app_module._retriever = mock_retriever
    app_module._llm = None

    _, _, _, _ = app_module.handle_query("forgiveness", 10)
    mock_retriever.search.assert_called_once_with("forgiveness", top_k=10)


def test_handle_query_row_structure():
    chunks = _make_chunks(1)
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks
    app_module._retriever = mock_retriever
    app_module._llm = None

    _, rows, _, _ = app_module.handle_query("test", 5)
    row = rows[0]
    # [#, title, scripture, date, snippet, match%, source_display]
    assert row[0] == 1
    assert row[1] == 'Sermon 0'
    assert row[2] == 'John 0:1'
    # Source file column should be basename only
    assert row[6] == 'Sermon 0.docx'


def test_handle_query_low_confidence_warning():
    chunks = _make_chunks(2, score=0.001)  # below LOW_CONFIDENCE_THRESHOLD
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks
    app_module._retriever = mock_retriever
    app_module._llm = None

    _, _, status, _ = app_module.handle_query("obscure topic", 5)
    assert '⚠️' in status or 'Low confidence' in status


def test_handle_query_normal_confidence_status():
    chunks = _make_chunks(3, score=0.025)  # above LOW_CONFIDENCE_THRESHOLD
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks
    app_module._retriever = mock_retriever
    app_module._llm = None

    _, _, status, _ = app_module.handle_query("grace", 5)
    assert '3' in status
    assert '⚠️' not in status


def test_handle_query_no_results():
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = []
    app_module._retriever = mock_retriever

    answer, rows, status, state = app_module.handle_query("xyzzy", 5)
    assert rows == []
    assert state == []


def test_handle_query_retriever_exception():
    mock_retriever = mock.MagicMock()
    mock_retriever.search.side_effect = RuntimeError("FAISS exploded")
    app_module._retriever = mock_retriever

    answer, rows, status, state = app_module.handle_query("grace", 5)
    assert 'error' in answer.lower() or 'error' in status.lower()


# ---------------------------------------------------------------------------
# on_row_select
# ---------------------------------------------------------------------------

def _make_select_event(row: int, col: int = 0):
    """Create a mock gr.SelectData-like event."""
    evt = mock.MagicMock()
    evt.index = [row, col]
    return evt


def test_on_row_select_no_chunks():
    evt = _make_select_event(0)
    result = app_module.on_row_select(evt, [])
    assert 'no' in result.lower() or 'not' in result.lower()


def test_on_row_select_out_of_range():
    chunks = _make_chunks(2)
    evt = _make_select_event(5)
    result = app_module.on_row_select(evt, chunks)
    assert 'no' in result.lower() or 'not' in result.lower() or 'selected' in result.lower()


def test_on_row_select_none_event():
    result = app_module.on_row_select(None, _make_chunks(3))
    assert result == ""


def test_on_row_select_missing_source():
    chunks = [{'source_file': '', 'title': 'Test'}]
    evt = _make_select_event(0)
    result = app_module.on_row_select(evt, chunks)
    assert 'not available' in result.lower() or 'no' in result.lower()


def test_on_row_select_file_not_on_disk():
    chunks = [{'source_file': '/nonexistent/path/Sermon.docx', 'title': 'Test'}]
    evt = _make_select_event(0)
    result = app_module.on_row_select(evt, chunks)
    assert 'not found' in result.lower() or 'could not' in result.lower()


def test_on_row_select_opens_file(tmp_path):
    # Create a real temporary file so path.exists() passes
    tmp_file = tmp_path / "Sermon Test.docx"
    tmp_file.write_text("test content")

    chunks = [{'source_file': str(tmp_file), 'title': 'Test'}]
    evt = _make_select_event(0)

    # Patch the platform-specific open call
    with mock.patch('subprocess.run') as mock_run, \
         mock.patch('sys.platform', 'linux'):
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = app_module.on_row_select(evt, chunks)

    assert 'Opened' in result
    assert 'Sermon Test.docx' in result


# ---------------------------------------------------------------------------
# _run_subprocess (archive handlers)
# ---------------------------------------------------------------------------

def test_run_subprocess_captures_output():
    result = app_module._run_subprocess([sys.executable, '-c', 'print("hello")'])
    assert 'hello' in result


def test_run_subprocess_captures_stderr():
    result = app_module._run_subprocess(
        [sys.executable, '-c', 'import sys; print("err", file=sys.stderr)']
    )
    assert 'err' in result


def test_run_subprocess_nonzero_exit():
    result = app_module._run_subprocess([sys.executable, '-c', 'import sys; sys.exit(42)'])
    assert 'exit code' in result or '42' in result


# ---------------------------------------------------------------------------
# process_new_files / full_rebuild — empty folder guard
# ---------------------------------------------------------------------------

def test_process_new_files_empty_folder():
    # Returns (summary, raw_log) tuple since Tier 1 refactor
    summary, _ = app_module.process_new_files("")
    assert 'enter' in summary.lower() or 'please' in summary.lower()


def test_full_rebuild_empty_folder():
    # Returns (summary, raw_log) tuple since Tier 1 refactor
    summary, _ = app_module.full_rebuild("")
    assert 'enter' in summary.lower() or 'please' in summary.lower()
