"""Tests for build/format_detect.py — magic byte detection."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build.format_detect import detect_format, classify_ole2

MAGIC_OLE2  = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
MAGIC_RTF   = b'{\\ rtf1'
MAGIC_OOXML = b'PK\x03\x04\x14\x00\x00\x00'


def _write_tmp(content: bytes, suffix: str = '.bin') -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(content)
        return f.name


def test_detect_ole2():
    path = _write_tmp(MAGIC_OLE2, '.doc')
    assert detect_format(path) == 'ole2'


def test_detect_rtf():
    path = _write_tmp(MAGIC_RTF, '.rtf')
    assert detect_format(path) == 'rtf'


def test_detect_ooxml():
    path = _write_tmp(MAGIC_OOXML, '.docx')
    assert detect_format(path) == 'ooxml'


def test_detect_unknown():
    path = _write_tmp(b'\x00\x01\x02\x03', '.bin')
    assert detect_format(path) == 'unknown'


def test_detect_missing_file():
    assert detect_format('/nonexistent/file.doc') == 'unknown'


def test_classify_ole2_pub():
    assert classify_ole2('something.pub') == 'ole2_pub'


def test_classify_ole2_word():
    assert classify_ole2('sermon.doc') == 'ole2_word'
    assert classify_ole2('sermon.DOC') == 'ole2_word'
