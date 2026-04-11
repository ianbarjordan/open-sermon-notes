"""Tests for build/parse_filename.py — metadata extraction from filename stems."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build.parse_filename import parse_filename


def test_scripture_first_pattern():
    result = parse_filename("1 Cor 7_1-5  Gifts That Never Go Out Of Style")
    assert result['pattern'] == 'scripture_first'
    assert result['scripture_ref'] is not None
    assert '1 Corinthians' in result['scripture_ref'] or 'Corinthians' in result['scripture_ref']
    assert result['title'] == 'Gifts That Never Go Out Of Style'


def test_date_yymmdd_pattern():
    result = parse_filename("050111 Lift up your heads")
    assert result['pattern'] == 'date_yymmdd'
    assert result['date'] == '2005-01-11'
    assert 'Lift' in result['title']


def test_date_mddyy_pattern():
    result = parse_filename("11-22-00 A Title Here")
    assert result['pattern'] == 'date_mddyy'
    assert result['date'] == '2000-11-22'


def test_numbered_series_pattern():
    result = parse_filename("03. The Brazen Laver")
    assert result['pattern'] == 'numbered_series'
    assert result['series_number'] == 3
    assert result['title'] == 'The Brazen Laver'


def test_plain_title_fallback():
    result = parse_filename("A Hero")
    assert result['pattern'] == 'plain_title'
    assert result['title'] == 'A Hero'
    assert result['scripture_ref'] is None
    assert result['date'] is None


def test_result_has_all_keys():
    result = parse_filename("Some Title")
    for key in ('raw_stem', 'title', 'scripture_ref', 'date', 'series_number', 'pattern'):
        assert key in result, f"Missing key: {key}"


def test_century_inference_2000s():
    # yy=05 → 2005
    result = parse_filename("050111 Test")
    assert result['date'].startswith('2005')


def test_century_inference_1900s():
    # yy=98 → 1998
    result = parse_filename("980611 Old Sermon")
    assert result['date'].startswith('1998')


def test_all_caps_title_lowercased():
    result = parse_filename("GRACE AND MERCY")
    assert result['title'] != 'GRACE AND MERCY', "ALL-CAPS titles should be title-cased"


def test_scripture_romans():
    result = parse_filename("Rom 8_28 All Things Work Together")
    assert result['pattern'] == 'scripture_first'
    assert 'Romans' in result['scripture_ref']
