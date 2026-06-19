"""Tests for build/ingest_files.py — quarantine pipeline filters."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build.ingest_files import (  # noqa: E402
    should_skip_silently,
    is_filename_flagged,
    count_faith_hits,
    compute_sha256,
    make_doc_id,
    _strip_surrogates,
    write_document_json,
)


# ---------------------------------------------------------------------------
# should_skip_silently
# ---------------------------------------------------------------------------

def test_skip_identifier():
    assert should_skip_silently(Path("foo.identifier"))


def test_skip_csv():
    assert should_skip_silently(Path("data.csv"))


def test_skip_md():
    assert should_skip_silently(Path("README.md"))


def test_no_skip_docx():
    assert not should_skip_silently(Path("sermon.docx"))


def test_no_skip_doc():
    assert not should_skip_silently(Path("sermon.doc"))


# ---------------------------------------------------------------------------
# is_filename_flagged
# ---------------------------------------------------------------------------

def test_flagged_tax():
    assert is_filename_flagged("2023 tax report")


def test_flagged_budget():
    assert is_filename_flagged("Annual Budget Meeting")


def test_flagged_obituary():
    assert is_filename_flagged("John Smith obituary")


def test_not_flagged_sermon():
    assert not is_filename_flagged("Grace and Forgiveness")


def test_not_flagged_faith():
    assert not is_filename_flagged("Jesus and the disciples")


# ---------------------------------------------------------------------------
# count_faith_hits
# ---------------------------------------------------------------------------

def test_faith_hits_sermon():
    text = "Jesus Christ died for our sins. The Lord is gracious. Scripture declares salvation."
    hits = count_faith_hits(text)
    assert hits >= 3


def test_faith_hits_zero():
    text = "The quarterly financial report shows a surplus in the budget line items."
    hits = count_faith_hits(text)
    assert hits == 0


def test_faith_hits_mixed():
    text = "Tax exemption for the church. Jesus saves."
    hits = count_faith_hits(text)
    assert hits >= 1


# ---------------------------------------------------------------------------
# make_doc_id
# ---------------------------------------------------------------------------

def test_make_doc_id_basic():
    assert make_doc_id("A Hero") == "a_hero"


def test_make_doc_id_special_chars():
    doc_id = make_doc_id("1 Cor 7:1-5 Grace & Glory!")
    # Should contain only lowercase alphanumeric and underscores
    import re
    assert re.match(r'^[a-z0-9_]+$', doc_id), f"Invalid doc_id: {doc_id!r}"


def test_make_doc_id_no_leading_trailing_underscores():
    doc_id = make_doc_id("___test___")
    assert not doc_id.startswith('_')
    assert not doc_id.endswith('_')


def test_make_doc_id_no_consecutive_underscores():
    doc_id = make_doc_id("Hello   World")
    assert '__' not in doc_id


# ---------------------------------------------------------------------------
# compute_sha256
# ---------------------------------------------------------------------------

def test_compute_sha256_consistent():
    import tempfile, hashlib
    content = b"Hello, sermon notes"
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(content)
        path = Path(f.name)
    result = compute_sha256(path)
    expected = hashlib.sha256(content).hexdigest()
    assert result == expected


def test_compute_sha256_different_files():
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as f1:
        f1.write(b"content one")
        p1 = Path(f1.name)
    with tempfile.NamedTemporaryFile(delete=False) as f2:
        f2.write(b"content two")
        p2 = Path(f2.name)
    assert compute_sha256(p1) != compute_sha256(p2)


# ---------------------------------------------------------------------------
# _strip_surrogates
# ---------------------------------------------------------------------------

def test_strip_surrogates_clean_text():
    text = "Grace and mercy from Jesus Christ."
    assert _strip_surrogates(text) == text


def test_strip_surrogates_removes_lone_surrogate():
    # Insert a lone surrogate (U+DB00) — valid Python str, invalid UTF-8
    text = "Hello \udB00 world"
    result = _strip_surrogates(text)
    assert '\udB00' not in result
    assert 'Hello' in result
    assert 'world' in result


def test_strip_surrogates_result_is_utf8_encodable():
    text = "Sermon \udb00\udc00 text with surrogates"
    result = _strip_surrogates(text)
    # Should not raise
    result.encode('utf-8')


def test_strip_surrogates_empty_string():
    assert _strip_surrogates('') == ''


# ---------------------------------------------------------------------------
# write_document_json — surrogate handling
# ---------------------------------------------------------------------------

def test_write_document_json_with_surrogates():
    """write_document_json must not crash when text contains lone surrogates."""
    import json, tempfile
    doc = {
        'doc_id':        'test_surrogate',
        'source_file':   'test.docx',
        'title':         'Test',
        'scripture_ref': None,
        'date':          None,
        'format':        'ooxml_doc',
        'word_count':    10,
        'text':          'Valid text \udb00 with surrogate.',
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        write_document_json(doc, tmpdir)
        out = Path(tmpdir) / 'test_surrogate.json'
        assert out.exists()
        loaded = json.loads(out.read_text(encoding='utf-8'))
        assert loaded['doc_id'] == 'test_surrogate'
        assert '\udb00' not in loaded['text']


# ---------------------------------------------------------------------------
# quarantine — PermissionError tolerance
# ---------------------------------------------------------------------------

def test_quarantine_skips_existing_file():
    """quarantine() must not crash when destination already exists."""
    import tempfile
    from build.format_detect import detect_format  # noqa
    from build.ingest_files import quarantine as quarantine_fn

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a source file
        src = Path(tmpdir) / "sermon.doc"
        src.write_bytes(b"fake content")
        qroot = str(Path(tmpdir) / "quarantine")

        # First call — should succeed
        quarantine_fn(src, 'manual_review', qroot)
        dest = Path(qroot) / 'manual_review' / 'sermon.doc'
        assert dest.exists()

        # Second call — file already exists, must not raise
        quarantine_fn(src, 'manual_review', qroot)
