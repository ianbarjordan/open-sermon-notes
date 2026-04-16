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
    # Retriever is always called with MAX_TOP_K so auto-expansion has the full pool
    from app.config import MAX_TOP_K
    mock_retriever.search.assert_called_once_with("grace", top_k=MAX_TOP_K)


def test_handle_query_always_fetches_max_top_k():
    """Slider value does not limit the retriever call — only the minimum shown."""
    from app.config import MAX_TOP_K
    chunks = _make_chunks(5)
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks
    app_module._retriever = mock_retriever
    app_module._llm = None

    app_module.handle_query("forgiveness", top_k=3)
    mock_retriever.search.assert_called_once_with("forgiveness", top_k=MAX_TOP_K)


def test_handle_query_slider_sets_minimum():
    """Slider value is the floor: results below AUTO_EXPAND_THRESHOLD beyond
    the slider value are not included."""
    from app.config import AUTO_EXPAND_THRESHOLD
    # 5 chunks: first 2 above threshold, next 3 below
    high = AUTO_EXPAND_THRESHOLD + 0.005
    low  = AUTO_EXPAND_THRESHOLD - 0.005
    chunks = (
        _make_chunks(2, score=high) +
        _make_chunks(3, score=low)
    )
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks
    app_module._retriever = mock_retriever
    app_module._llm = None

    # Slider = 1 → base is 1, but 1 more is high-confidence → 2 rows shown
    # State holds the full fetched pool (5), not just the visible slice
    _, rows, _, state = app_module.handle_query("grace", top_k=1)
    assert len(rows) == 2
    assert len(state) == 5  # full pool stored in state


def test_handle_query_auto_expand_status():
    """Status line mentions auto-expansion when extra high-confidence results are added."""
    from app.config import AUTO_EXPAND_THRESHOLD
    high = AUTO_EXPAND_THRESHOLD + 0.005
    chunks = _make_chunks(5, score=high)
    mock_retriever = mock.MagicMock()
    mock_retriever.search.return_value = chunks
    app_module._retriever = mock_retriever
    app_module._llm = None

    # Slider = 2, but all 5 chunks are above AUTO_EXPAND_THRESHOLD
    _, _, status, state = app_module.handle_query("grace", top_k=2)
    assert len(state) == 5
    assert 'additional' in status.lower() or '5' in status


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
# _extract_row_index
# ---------------------------------------------------------------------------

def test_extract_row_index_select_data_list():
    """Standard Gradio 5 SelectData: evt.index = [row, col]."""
    evt = mock.MagicMock()
    evt.index = [3, 1]
    assert app_module._extract_row_index(evt) == 3


def test_extract_row_index_select_data_int():
    """Some Gradio builds: evt.index is a plain int."""
    evt = mock.MagicMock()
    evt.index = 7
    assert app_module._extract_row_index(evt) == 7


def test_extract_row_index_plain_list():
    """When Gradio passes a plain list (row, col) — no .index attribute that matters."""
    assert app_module._extract_row_index([2, 0]) == 2


def test_extract_row_index_callable_index_is_ignored():
    """A plain Python list has .index() as a callable method — must not crash."""
    # Python list: evt.index is the list.index() *method*, not a row number
    evt = [5, 0]  # plain list — evt.index is callable
    # Should fall through to the isinstance(evt, list) branch → 5
    assert app_module._extract_row_index(evt) == 5


def test_extract_row_index_none_event():
    """None returns None without error."""
    assert app_module._extract_row_index(None) is None


# ---------------------------------------------------------------------------
# expand_results
# ---------------------------------------------------------------------------

def test_expand_results_empty_state():
    rows, status = app_module.expand_results(5, [])
    assert rows == []
    assert status == ""


def test_expand_results_shows_base():
    from app.config import AUTO_EXPAND_THRESHOLD
    chunks = _make_chunks(10, score=AUTO_EXPAND_THRESHOLD - 0.005)  # all below threshold
    rows, status = app_module.expand_results(4, chunks)
    assert len(rows) == 4  # exactly slider value, no auto-expansion


def test_expand_results_auto_expands():
    from app.config import AUTO_EXPAND_THRESHOLD
    high = AUTO_EXPAND_THRESHOLD + 0.005
    chunks = _make_chunks(5, score=high)
    rows, status = app_module.expand_results(2, chunks)
    # All 5 are above threshold → all shown
    assert len(rows) == 5
    assert 'additional' in status.lower() or '5' in status


def test_expand_results_slider_increase_shows_more():
    from app.config import AUTO_EXPAND_THRESHOLD
    low = AUTO_EXPAND_THRESHOLD - 0.005
    chunks = _make_chunks(10, score=low)
    rows_3, _ = app_module.expand_results(3, chunks)
    rows_8, _ = app_module.expand_results(8, chunks)
    assert len(rows_3) == 3
    assert len(rows_8) == 8


# ---------------------------------------------------------------------------
# on_row_select
# ---------------------------------------------------------------------------

def _make_select_event(row: int, col: int = 0):
    """Create a mock gr.SelectData-like event (index is a non-callable attribute)."""
    evt = mock.MagicMock()
    evt.index = [row, col]  # MagicMock attribute — not callable
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


def test_on_row_select_file_not_on_disk(tmp_path):
    # Use a path that is guaranteed not to exist (rather than a Unix absolute path,
    # which resolves differently on Windows)
    missing = tmp_path / "does_not_exist" / "Sermon.docx"
    chunks = [{'source_file': str(missing), 'title': 'Test'}]
    evt = _make_select_event(0)
    result = app_module.on_row_select(evt, chunks)
    assert 'not found' in result.lower() or 'could not' in result.lower()


def test_on_row_select_opens_file_linux(tmp_path):
    """Non-Windows path: uses subprocess.run(['xdg-open', ...])."""
    tmp_file = tmp_path / "Sermon Test.docx"
    tmp_file.write_text("test content")
    chunks = [{'source_file': str(tmp_file), 'title': 'Test'}]
    evt = _make_select_event(0)

    with mock.patch('subprocess.run') as mock_run, \
         mock.patch('sys.platform', 'linux'):
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = app_module.on_row_select(evt, chunks)

    assert 'Opened' in result
    assert 'Sermon Test.docx' in result


def test_on_row_select_opens_file_windows(tmp_path):
    """Windows path: uses os.startfile, NOT subprocess."""
    tmp_file = tmp_path / "Sermon Test.docx"
    tmp_file.write_text("test content")
    chunks = [{'source_file': str(tmp_file), 'title': 'Test'}]
    evt = _make_select_event(0)

    with mock.patch('os.startfile') as mock_startfile, \
         mock.patch('sys.platform', 'win32'):
        result = app_module.on_row_select(evt, chunks)

    mock_startfile.assert_called_once()
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
    summary, _ = app_module.process_new_files("")
    assert 'enter' in summary.lower() or 'please' in summary.lower()


def test_full_rebuild_empty_folder():
    summary, _ = app_module.full_rebuild("")
    assert 'enter' in summary.lower() or 'please' in summary.lower()


def test_process_new_files_invalid_path(tmp_path):
    """Non-existent directory returns a user-friendly error, not an exception."""
    bad_path = str(tmp_path / "does_not_exist")
    summary, raw = app_module.process_new_files(bad_path)
    assert 'not found' in summary.lower() or 'check' in summary.lower()
    assert raw == ""


def test_full_rebuild_invalid_path(tmp_path):
    bad_path = str(tmp_path / "does_not_exist")
    summary, raw = app_module.full_rebuild(bad_path)
    assert 'not found' in summary.lower() or 'check' in summary.lower()
    assert raw == ""


# ---------------------------------------------------------------------------
# open_file (number-input fallback handler)
# ---------------------------------------------------------------------------

def test_open_file_no_results():
    result = app_module.open_file(1, [])
    assert 'no search' in result.lower() or 'run a search' in result.lower()


def test_open_file_out_of_range():
    chunks = _make_chunks(2)
    result = app_module.open_file(5, chunks)
    assert 'does not exist' in result.lower() or 'result' in result.lower()


def test_open_file_missing_source():
    chunks = [{'source_file': '', 'title': 'Test'}]
    result = app_module.open_file(1, chunks)
    assert 'no file' in result.lower() or 'path' in result.lower()


def test_open_file_file_not_on_disk(tmp_path):
    missing = tmp_path / "nope" / "Sermon.docx"
    chunks = [{'source_file': str(missing), 'title': 'Test'}]
    result = app_module.open_file(1, chunks)
    assert 'not found' in result.lower()


def test_open_file_opens_on_linux(tmp_path):
    tmp_file = tmp_path / "Grace.docx"
    tmp_file.write_text("content")
    chunks = [{'source_file': str(tmp_file), 'title': 'Test'}]

    with mock.patch('subprocess.run') as mock_run, \
         mock.patch('sys.platform', 'linux'):
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = app_module.open_file(1, chunks)

    assert 'Opened' in result
    assert 'Grace.docx' in result


def test_open_file_opens_on_windows(tmp_path):
    """Windows path: must call os.startfile, not subprocess."""
    tmp_file = tmp_path / "Grace.docx"
    tmp_file.write_text("content")
    chunks = [{'source_file': str(tmp_file), 'title': 'Test'}]

    with mock.patch('os.startfile') as mock_startfile, \
         mock.patch('sys.platform', 'win32'):
        result = app_module.open_file(1, chunks)

    mock_startfile.assert_called_once()
    assert 'Opened' in result


# ---------------------------------------------------------------------------
# load_settings / save_settings
# ---------------------------------------------------------------------------

def test_settings_roundtrip(tmp_path, monkeypatch):
    """save_settings then load_settings returns the same dict."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(app_module, '_settings_path', lambda: settings_file)

    app_module.save_settings({'sermon_library_folder': r'C:\Sermons'})
    loaded = app_module.load_settings()
    assert loaded['sermon_library_folder'] == r'C:\Sermons'


def test_load_settings_missing_file(tmp_path, monkeypatch):
    """Missing settings file returns empty dict, not an error."""
    monkeypatch.setattr(app_module, '_settings_path',
                        lambda: tmp_path / "nonexistent.json")
    assert app_module.load_settings() == {}


def test_save_settings_creates_parent(tmp_path, monkeypatch):
    deep = tmp_path / "a" / "b" / "settings.json"
    monkeypatch.setattr(app_module, '_settings_path', lambda: deep)
    app_module.save_settings({'key': 'value'})
    assert deep.exists()


# ---------------------------------------------------------------------------
# _parse_ingest_counts
# ---------------------------------------------------------------------------

_SAMPLE_INGEST_LOG = """
Found 253 files in 'SampleData'
Platform: Windows

--- Ingest Summary ---
  accepted                  153
  skipped                    21
  too_short                  19
  non_faith                  18
  filename_flagged           15
  format_pub                 13
  manual_review              10
  worship_slides              3
  duplicates                  1
  TOTAL                     253
"""


def test_parse_ingest_counts_accepted():
    counts = app_module._parse_ingest_counts(_SAMPLE_INGEST_LOG)
    assert counts['accepted'] == 153


def test_parse_ingest_counts_manual_review():
    counts = app_module._parse_ingest_counts(_SAMPLE_INGEST_LOG)
    assert counts['manual_review'] == 10


def test_parse_ingest_counts_total_ignored():
    """TOTAL line should not appear as a count key."""
    counts = app_module._parse_ingest_counts(_SAMPLE_INGEST_LOG)
    assert 'TOTAL' not in counts


def test_parse_ingest_counts_empty_log():
    assert app_module._parse_ingest_counts("no summary here") == {}


# ---------------------------------------------------------------------------
# _build_run_summary
# ---------------------------------------------------------------------------

def test_build_run_summary_success():
    summary = app_module._build_run_summary(_SAMPLE_INGEST_LOG)
    assert '153' in summary
    assert '✅' in summary


def test_build_run_summary_word_blocked():
    log = _SAMPLE_INGEST_LOG + "\nWord blocked by administrator\n[exit code: 1]"
    summary = app_module._build_run_summary(log)
    assert '⚠️' in summary
    assert 'word' in summary.lower() or 'unblock' in summary.lower()


def test_build_run_summary_generic_exit_code():
    summary = app_module._build_run_summary("some output\n[exit code: 1]")
    assert '⚠️' in summary


def test_build_run_summary_no_counts_no_error():
    """No summary block, no error → generic completion message."""
    summary = app_module._build_run_summary("", operation='Rebuild')
    assert 'Rebuild' in summary or '✅' in summary


# ---------------------------------------------------------------------------
# unblock_library
# ---------------------------------------------------------------------------

def test_unblock_library_empty_folder():
    summary, _ = app_module.unblock_library("")
    assert 'enter' in summary.lower() or 'please' in summary.lower()


def test_unblock_library_invalid_path(tmp_path):
    bad = str(tmp_path / "missing")
    summary, _ = app_module.unblock_library(bad)
    assert 'not found' in summary.lower()


def test_unblock_library_non_windows(tmp_path):
    with mock.patch('sys.platform', 'linux'):
        summary, _ = app_module.unblock_library(str(tmp_path))
    assert 'windows' in summary.lower()


def test_unblock_library_windows_success(tmp_path):
    with mock.patch('sys.platform', 'win32'), \
         mock.patch('subprocess.run') as mock_run:
        mock_run.return_value = mock.MagicMock(
            returncode=0, stdout="Done.\n", stderr=""
        )
        summary, raw = app_module.unblock_library(str(tmp_path))

    assert '✅' in summary
    assert 'process new files' in summary.lower() or 'retry' in summary.lower()


def test_unblock_library_windows_failure(tmp_path):
    with mock.patch('sys.platform', 'win32'), \
         mock.patch('subprocess.run') as mock_run:
        mock_run.return_value = mock.MagicMock(
            returncode=1, stdout="", stderr="Access denied"
        )
        summary, raw = app_module.unblock_library(str(tmp_path))

    assert '⚠️' in summary
    assert 'access denied' in raw.lower()


# ---------------------------------------------------------------------------
# browse_folder
# ---------------------------------------------------------------------------

def test_browse_folder_non_windows():
    with mock.patch('sys.platform', 'linux'):
        result = app_module.browse_folder()
    assert result == ''


def test_browse_folder_windows_returns_path(tmp_path):
    with mock.patch('sys.platform', 'win32'), \
         mock.patch('subprocess.run') as mock_run:
        mock_run.return_value = mock.MagicMock(
            returncode=0, stdout=str(tmp_path)
        )
        result = app_module.browse_folder()
    assert result == str(tmp_path)


def test_browse_folder_windows_cancelled():
    """User cancels dialog → empty string returned."""
    with mock.patch('sys.platform', 'win32'), \
         mock.patch('subprocess.run') as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0, stdout='')
        result = app_module.browse_folder()
    assert result == ''


# ---------------------------------------------------------------------------
# Quarantine handlers
# ---------------------------------------------------------------------------

def _setup_quarantine(tmp_path, buckets: dict[str, list[str]]) -> Path:
    """Create a quarantine directory tree under tmp_path."""
    root = tmp_path / "raw" / "quarantine"
    for reason, files in buckets.items():
        bucket = root / reason
        bucket.mkdir(parents=True)
        for fname in files:
            (bucket / fname).write_text("dummy content")
    return root


def test_list_quarantine_returns_buckets(tmp_path):
    root = _setup_quarantine(tmp_path, {
        'manual_review': ['a.doc', 'b.doc'],
        'duplicates': ['c.docx'],
    })
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.list_quarantine()
    assert set(result.keys()) == {'manual_review', 'duplicates'}
    assert set(result['manual_review']) == {'a.doc', 'b.doc'}


def test_list_quarantine_sorted_by_count(tmp_path):
    root = _setup_quarantine(tmp_path, {
        'too_short': ['x.docx'],
        'duplicates': ['a.docx', 'b.docx', 'c.docx'],
        'non_faith': ['d.docx', 'e.docx'],
    })
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.list_quarantine()
    counts = [len(v) for v in result.values()]
    assert counts == sorted(counts, reverse=True)


def test_list_quarantine_empty_root(tmp_path):
    missing = tmp_path / "raw" / "quarantine"
    with mock.patch.object(app_module, '_quarantine_root', return_value=missing):
        result = app_module.list_quarantine()
    assert result == {}


def test_list_quarantine_skips_empty_buckets(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    (root / "empty_bucket").mkdir(parents=True)
    (root / "non_faith").mkdir(parents=True)
    (root / "non_faith" / "sermon.docx").write_text("content")
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.list_quarantine()
    assert 'empty_bucket' not in result
    assert 'non_faith' in result


def test_ignore_quarantine_file_removes_file(tmp_path):
    root = _setup_quarantine(tmp_path, {'duplicates': ['dup.docx']})
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.ignore_quarantine_file('duplicates', 'dup.docx')
    assert not (root / 'duplicates' / 'dup.docx').exists()
    assert 'ignored' in result.lower() or 'removed' in result.lower()


def test_ignore_quarantine_file_already_gone(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    root.mkdir(parents=True)
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.ignore_quarantine_file('duplicates', 'ghost.docx')
    assert 'already' in result.lower() or 'removed' in result.lower()


def test_get_quarantine_summary_no_files(tmp_path):
    missing = tmp_path / "raw" / "quarantine"
    with mock.patch.object(app_module, '_quarantine_root', return_value=missing):
        result = app_module.get_quarantine_summary()
    assert 'no files' in result.lower() or 'everything' in result.lower()


def test_get_quarantine_summary_with_files(tmp_path):
    root = _setup_quarantine(tmp_path, {
        'manual_review': ['a.doc', 'b.doc'],
        'duplicates': ['c.docx'],
    })
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.get_quarantine_summary()
    assert '3' in result   # total
    assert '2' in result   # manual_review count


def test_force_ingest_file_no_library(tmp_path):
    root = _setup_quarantine(tmp_path, {'manual_review': ['sermon.doc']})
    with mock.patch.object(app_module, '_quarantine_root', return_value=root), \
         mock.patch.object(app_module, 'load_settings', return_value={'sermon_library_folder': ''}):
        result = app_module.force_ingest_file('manual_review', 'sermon.doc')
    assert 'not set' in result.lower() or 'library' in result.lower()


def test_force_ingest_file_missing_from_quarantine(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    root.mkdir(parents=True)
    with mock.patch.object(app_module, '_quarantine_root', return_value=root), \
         mock.patch.object(app_module, 'load_settings',
                           return_value={'sermon_library_folder': str(tmp_path)}):
        result = app_module.force_ingest_file('manual_review', 'ghost.doc')
    assert 'not found' in result.lower()


# ---------------------------------------------------------------------------
# batch_ignore_quarantine
# ---------------------------------------------------------------------------

def test_batch_ignore_removes_all_files(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    bucket = root / "too_short"
    bucket.mkdir(parents=True)
    for i in range(3):
        (bucket / f"sermon_{i}.docx").write_text("x")
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.batch_ignore_quarantine('too_short')
    assert "3" in result
    assert list(bucket.iterdir()) == []


def test_batch_ignore_missing_bucket(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    root.mkdir(parents=True)
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.batch_ignore_quarantine('nonexistent')
    assert 'not found' in result.lower()


def test_batch_ignore_empty_bucket(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    bucket = root / "too_short"
    bucket.mkdir(parents=True)
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        result = app_module.batch_ignore_quarantine('too_short')
    assert 'empty' in result.lower()


# ---------------------------------------------------------------------------
# request_batch_action / execute_batch_action / cancel_batch_action
# ---------------------------------------------------------------------------

def test_request_batch_action_ignore_returns_pending_state():
    pending, msg, col_update = app_module.request_batch_action('ignore', 'too_short', 5)
    assert pending == {'action': 'ignore', 'reason': 'too_short', 'count': 5}
    assert '5' in msg
    assert col_update.get('visible') is True  # gr.update dict


def test_request_batch_action_force_returns_pending_state():
    pending, msg, col_update = app_module.request_batch_action('force', 'manual_review', 10)
    assert pending == {'action': 'force', 'reason': 'manual_review', 'count': 10}
    assert '10' in msg
    assert col_update.get('visible') is True


def test_request_batch_action_large_count_adds_warning():
    pending, msg, _col = app_module.request_batch_action('force', 'too_short', 200)
    assert 'minutes' in msg.lower() or '200' in msg


def test_execute_batch_action_clears_pending_and_hides_panel(tmp_path):
    root = tmp_path / "raw" / "quarantine"
    bucket = root / "too_short"
    bucket.mkdir(parents=True)
    (bucket / "a.docx").write_text("x")
    pending = {'action': 'ignore', 'reason': 'too_short', 'count': 1}
    with mock.patch.object(app_module, '_quarantine_root', return_value=root):
        cleared, confirm_msg, col_update, result = app_module.execute_batch_action(pending)
    assert cleared == {'action': None, 'reason': None, 'count': 0}
    assert confirm_msg == ""
    assert col_update.get('visible') is False
    assert '1' in result or 'deleted' in result.lower() or '✓' in result


def test_execute_batch_action_with_empty_pending():
    cleared, confirm_msg, col_update, result = app_module.execute_batch_action(
        {'action': None, 'reason': None, 'count': 0}
    )
    assert cleared == {'action': None, 'reason': None, 'count': 0}
    assert col_update.get('visible') is False


def test_cancel_batch_action_clears_state():
    cleared, confirm_msg, col_update, result = app_module.cancel_batch_action()
    assert cleared == {'action': None, 'reason': None, 'count': 0}
    assert confirm_msg == ""
    assert col_update.get('visible') is False
    assert result == ""
