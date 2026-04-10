"""
parse_filename.py — Extract structured metadata from sermon filename stems.

Usage:
    python build/parse_filename.py --stem "1 Cor 7_1-5  Gifts That Never Go Out Of Style"
    python build/parse_filename.py --stem "050111 Lift up your heads 1 signs"
    python build/parse_filename.py --dir SampleData/
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from build.normalize_scripture import normalize_book, parse_reference  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_century(two_digit_year: int) -> int:
    """0-24 → 2000, 25-99 → 1900."""
    return 2000 if two_digit_year <= 24 else 1900


def _clean_title(raw: str) -> str:
    """Remove (2)/(3) duplicate suffixes, normalize whitespace, title-case ALL-CAPS."""
    # Strip trailing copy markers like "(2)" or " 2" at end
    cleaned = re.sub(r'\s*\(\d+\)\s*$', '', raw).strip()
    cleaned = re.sub(r'\s+\d+\s*$', '', cleaned).strip()
    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # If ALL CAPS, title-case it
    if cleaned.isupper() and len(cleaned) > 2:
        cleaned = cleaned.title()
    return cleaned


def _title_from_remainder(remainder: str) -> str:
    """Strip leading separators/spaces and clean a title fragment."""
    remainder = re.sub(r'^[\s_\-]+', '', remainder)
    return _clean_title(remainder)


# ---------------------------------------------------------------------------
# Pattern matchers (priority order)
# ---------------------------------------------------------------------------

# Pattern 1: Scripture-first  e.g. "1 Cor 7_1-5  Gifts That Never Go Out Of Style"
_SCRIPTURE_FIRST_RE = re.compile(
    r'^(?P<book>[1-3]?\s*[A-Za-z]+)\s+'   # book token
    r'(?P<chapter>\d+)'                    # chapter
    r'[_:v]'                               # separator
    r'(?P<verse_start>\d+)'               # verse start
    r'(?:-\d+)?[Ff]{0,2}'                 # optional range/FF
    r'(?P<rest>.*)',
    re.IGNORECASE,
)

# Pattern 2: Date YYMMDD at start  e.g. "050111 Lift up your heads"
_DATE_YYMMDD_RE = re.compile(
    r'^(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})\s+(?P<rest>.+)$'
)

# Pattern 3: Date MM-DD-YY  e.g. "11-22-00", "4-11-00 Title"
_DATE_MDDYY_RE = re.compile(
    r'^(?P<mm>\d{1,2})-(?P<dd>\d{2})-(?P<yy>\d{2})(?P<rest>.*)$'
)

# Pattern 4: Numbered series  e.g. "03. The Brazen Laver", "73. Title"
_NUMBERED_RE = re.compile(
    r'^(?P<num>\d{1,3})\.\s+(?P<rest>.+)$'
)


def _try_scripture_first(stem: str) -> dict | None:
    m = _SCRIPTURE_FIRST_RE.match(stem)
    if not m:
        return None
    book_tok = m.group('book').strip()
    canonical = normalize_book(book_tok)
    if canonical is None:
        return None

    # Reconstruct the scripture ref portion
    raw_ref = stem[:m.end('verse_start')].strip()
    # Handle optional range suffix
    suffix_match = re.match(r'.*(?P<range>-\d+[Ff]{0,2}|[Ff]{1,2})', stem[:m.start('rest')])
    full_ref_raw = stem[:m.start('rest')].strip()
    ref = parse_reference(full_ref_raw)
    if ref is None:
        # Fallback: at minimum "Book chapter:verse"
        chapter = m.group('chapter')
        verse = m.group('verse_start')
        ref = f"{canonical} {chapter}:{verse}"

    title_raw = m.group('rest')
    title = _title_from_remainder(title_raw) if title_raw.strip() else canonical

    return {
        'raw_stem':      stem,
        'title':         title,
        'scripture_ref': ref,
        'date':          None,
        'series_number': None,
        'pattern':       'scripture_first',
    }


def _try_date_yymmdd(stem: str) -> dict | None:
    m = _DATE_YYMMDD_RE.match(stem)
    if not m:
        return None
    yy = int(m.group('yy'))
    mm = int(m.group('mm'))
    dd = int(m.group('dd'))
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    year = _infer_century(yy) + yy
    date = f"{year:04d}-{mm:02d}-{dd:02d}"
    title = _title_from_remainder(m.group('rest'))

    return {
        'raw_stem':      stem,
        'title':         title,
        'scripture_ref': None,
        'date':          date,
        'series_number': None,
        'pattern':       'date_yymmdd',
    }


def _try_date_mddyy(stem: str) -> dict | None:
    m = _DATE_MDDYY_RE.match(stem)
    if not m:
        return None
    mm = int(m.group('mm'))
    dd = int(m.group('dd'))
    yy = int(m.group('yy'))
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    year = _infer_century(yy) + yy
    date = f"{year:04d}-{mm:02d}-{dd:02d}"
    rest = m.group('rest').strip()
    title = _title_from_remainder(rest) if rest else None

    return {
        'raw_stem':      stem,
        'title':         title,
        'scripture_ref': None,
        'date':          date,
        'series_number': None,
        'pattern':       'date_mddyy',
    }


def _try_numbered(stem: str) -> dict | None:
    m = _NUMBERED_RE.match(stem)
    if not m:
        return None
    title = _clean_title(m.group('rest'))
    return {
        'raw_stem':      stem,
        'title':         title,
        'scripture_ref': None,
        'date':          None,
        'series_number': int(m.group('num')),
        'pattern':       'numbered_series',
    }


def _plain_title(stem: str) -> dict:
    return {
        'raw_stem':      stem,
        'title':         _clean_title(stem),
        'scripture_ref': None,
        'date':          None,
        'series_number': None,
        'pattern':       'plain_title',
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_filename(stem: str) -> dict:
    """Extract structured metadata from a filename stem.

    Returns a dict with keys:
        raw_stem, title, scripture_ref, date, series_number, pattern
    """
    for fn in (
        _try_scripture_first,
        _try_date_yymmdd,
        _try_date_mddyy,
        _try_numbered,
    ):
        result = fn(stem)
        if result is not None:
            return result
    return _plain_title(stem)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Parse sermon filename stems into structured metadata.')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--stem', metavar='TEXT', help='Parse a single stem, print JSON')
    group.add_argument('--dir',  metavar='PATH', help='Parse all files in directory')
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.stem:
        result = parse_filename(args.stem)
        print(json.dumps(result, indent=2))
        return

    root = Path(args.dir)
    if not root.is_dir():
        print(f"ERROR: {args.dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    pattern_counts: dict[str, int] = {}
    for entry in sorted(root.iterdir()):
        if entry.is_file():
            result = parse_filename(entry.stem)
            p = result['pattern']
            pattern_counts[p] = pattern_counts.get(p, 0) + 1
            print(json.dumps(result))

    print("\n--- Pattern summary ---", file=sys.stderr)
    for pat, n in sorted(pattern_counts.items()):
        print(f"  {pat:20s} {n}", file=sys.stderr)


if __name__ == '__main__':
    main()
