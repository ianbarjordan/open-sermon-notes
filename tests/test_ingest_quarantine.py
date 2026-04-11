"""Tests for 01_ingest_files.py — quarantine pipeline filters."""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load 01_ingest_files.py via importlib (numeric prefix workaround)
_spec = importlib.util.spec_from_file_location(
    "ingest01",
    str(Path(__file__).resolve().parent.parent / "build" / "01_ingest_files.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

should_skip_silently = _mod.should_skip_silently
is_filename_flagged  = _mod.is_filename_flagged
count_faith_hits     = _mod.count_faith_hits
compute_sha256       = _mod.compute_sha256
make_doc_id          = _mod.make_doc_id


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
