"""Tests for app/retriever.py — FTS5 query sanitizer and RRF fusion logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.retriever import sanitize_fts_query, Retriever


# ---------------------------------------------------------------------------
# sanitize_fts_query
# ---------------------------------------------------------------------------

def test_sanitize_basic_query():
    result = sanitize_fts_query("grace forgiveness")
    assert '"grace"' in result
    assert '"forgiveness"' in result


def test_sanitize_removes_short_tokens():
    # Tokens with len < 3 are stripped; len >= 3 are kept
    # "in" (2) and "a" (1) are stripped; "the" (3) and "grace" (5) are kept
    result = sanitize_fts_query("in a the grace")
    assert '"grace"' in result
    assert '"the"' in result      # 3 chars — kept by >= 3 rule
    assert '"in"' not in result   # 2 chars — stripped
    assert '"a"' not in result    # 1 char  — stripped


def test_sanitize_escapes_special_chars():
    # These chars should not appear in the output unescaped
    result = sanitize_fts_query('what "about" this-query (test)')
    # Should still produce a valid FTS5 expression
    assert isinstance(result, str)
    assert len(result) > 0


def test_sanitize_empty_query():
    result = sanitize_fts_query("")
    assert result == '""'


def test_sanitize_all_short_tokens():
    result = sanitize_fts_query("a b c")
    assert result == '""'


def test_sanitize_or_joined():
    result = sanitize_fts_query("grace mercy love")
    parts = result.split(' OR ')
    assert len(parts) == 3


# ---------------------------------------------------------------------------
# Retriever.rrf_fuse (pure logic, no artifacts needed)
# ---------------------------------------------------------------------------

class _MockRetriever:
    """Minimal stand-in that exposes rrf_fuse without loading real artifacts."""
    rrf_fuse = Retriever.rrf_fuse


def test_rrf_fuse_combines_lists():
    # A chunk that appears in both lists should have a higher score
    dense  = [{'chunk_id': 'a::0'}, {'chunk_id': 'b::0'}]
    sparse = [{'chunk_id': 'a::0'}, {'chunk_id': 'c::0'}]
    fused = Retriever.rrf_fuse(None, dense, sparse)  # None for self — method uses no self attrs
    scores = dict(fused)
    assert scores['a::0'] > scores['b::0'], "Chunk in both lists should outscore chunk in one list"
    assert scores['a::0'] > scores['c::0']


def test_rrf_fuse_empty_lists():
    fused = Retriever.rrf_fuse(None, [], [])
    assert fused == []


def test_rrf_fuse_only_dense():
    dense  = [{'chunk_id': 'x::0'}, {'chunk_id': 'y::0'}]
    fused  = Retriever.rrf_fuse(None, dense, [])
    ids = [cid for cid, _ in fused]
    assert 'x::0' in ids
    assert 'y::0' in ids


def test_rrf_fuse_rank_order():
    # First item in each list should rank higher than last
    dense  = [{'chunk_id': 'top::0'}, {'chunk_id': 'mid::0'}, {'chunk_id': 'bot::0'}]
    sparse = []
    fused  = Retriever.rrf_fuse(None, dense, sparse)
    scores = dict(fused)
    assert scores['top::0'] > scores['mid::0'] > scores['bot::0']
