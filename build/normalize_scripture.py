"""
normalize_scripture.py — Map Bible book abbreviations to canonical names.

Usage:
    python build/normalize_scripture.py --ref "1 Cor 7_1-5"
    python build/normalize_scripture.py --list
    python build/normalize_scripture.py --audit SampleData/
"""
import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical book names (ordered OT then NT)
# ---------------------------------------------------------------------------
CANONICAL_BOOKS = [
    # OT
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth",
    "1 Samuel", "2 Samuel", "1 Kings", "2 Kings",
    "1 Chronicles", "2 Chronicles",
    "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon",
    "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    # NT
    "Matthew", "Mark", "Luke", "John", "Acts",
    "Romans",
    "1 Corinthians", "2 Corinthians",
    "Galatians", "Ephesians", "Philippians", "Colossians",
    "1 Thessalonians", "2 Thessalonians",
    "1 Timothy", "2 Timothy",
    "Titus", "Philemon", "Hebrews", "James",
    "1 Peter", "2 Peter",
    "1 John", "2 John", "3 John",
    "Jude", "Revelation",
]

# ---------------------------------------------------------------------------
# Alias table — maps lowercase alias → canonical name
# ---------------------------------------------------------------------------
# Each tuple: (canonical, [aliases...])
_ALIAS_PAIRS = [
    ("Genesis",          ["gen", "gn", "ge"]),
    ("Exodus",           ["ex", "exo", "exod"]),
    ("Leviticus",        ["lev", "lv"]),
    ("Numbers",          ["num", "nu", "nb"]),
    ("Deuteronomy",      ["deut", "dt", "deu"]),
    ("Joshua",           ["josh", "jos"]),
    ("Judges",           ["judg", "jdg", "jg"]),
    ("Ruth",             ["ruth", "ru"]),
    ("1 Samuel",         ["1sam", "1sa", "1 sam", "1 sa", "1samuel", "1s"]),
    ("2 Samuel",         ["2sam", "2sa", "2 sam", "2 sa", "2samuel"]),
    ("1 Kings",          ["1kgs", "1ki", "1 kings", "1 ki", "1kings"]),
    ("2 Kings",          ["2kgs", "2ki", "2 kings", "2 ki", "2kings"]),
    ("1 Chronicles",     ["1chron", "1chr", "1ch", "1 chr", "1 chron", "1chronicles"]),
    ("2 Chronicles",     ["2chron", "2chr", "2ch", "2 chr", "2 chron", "2chronicles"]),
    ("Ezra",             ["ezra", "ezr"]),
    ("Nehemiah",         ["neh", "ne"]),
    ("Esther",           ["esth", "es"]),
    ("Job",              ["job", "jb"]),
    ("Psalms",           ["ps", "psa", "psalm", "psalms", "pss"]),
    ("Proverbs",         ["prov", "pro", "prv", "pr"]),
    ("Ecclesiastes",     ["eccl", "ecc", "ec", "qoh"]),
    ("Song of Solomon",  ["song", "sos", "ss", "cant", "canticles", "sol"]),
    ("Isaiah",           ["isa", "is"]),
    ("Jeremiah",         ["jer", "je"]),
    ("Lamentations",     ["lam", "la"]),
    ("Ezekiel",          ["ezek", "eze", "ez"]),
    ("Daniel",           ["dan", "dn"]),
    ("Hosea",            ["hos", "ho"]),
    ("Joel",             ["joel", "jl"]),
    ("Amos",             ["amos", "am"]),
    ("Obadiah",          ["obad", "ob"]),
    ("Jonah",            ["jonah", "jon"]),
    ("Micah",            ["mic", "mi"]),
    ("Nahum",            ["nah", "na"]),
    ("Habakkuk",         ["hab", "hb"]),
    ("Zephaniah",        ["zeph", "zep", "zp"]),
    ("Haggai",           ["hag", "hg"]),
    ("Zechariah",        ["zech", "zec", "zc"]),
    ("Malachi",          ["mal", "ml"]),
    # NT
    ("Matthew",          ["matt", "mt", "mat"]),
    ("Mark",             ["mark", "mk", "mr"]),
    ("Luke",             ["luke", "lk", "lu"]),
    ("John",             ["john", "jn", "joh"]),
    ("Acts",             ["acts", "ac"]),
    ("Romans",           ["rom", "ro", "rm"]),
    ("1 Corinthians",    ["1cor", "1co", "1 cor", "1 co", "1corinthians", "1corinth"]),
    ("2 Corinthians",    ["2cor", "2co", "2 cor", "2 co", "2corinthians", "2corinth"]),
    ("Galatians",        ["gal", "ga"]),
    ("Ephesians",        ["eph", "ephes"]),
    ("Philippians",      ["phil", "php", "pp"]),
    ("Colossians",       ["col", "co"]),
    ("1 Thessalonians",  ["1thess", "1thes", "1th", "1 thess", "1 thes", "1thessalonians"]),
    ("2 Thessalonians",  ["2thess", "2thes", "2th", "2 thess", "2 thes", "2thessalonians"]),
    ("1 Timothy",        ["1tim", "1ti", "1 tim", "1timothy"]),
    ("2 Timothy",        ["2tim", "2ti", "2 tim", "2timothy"]),
    ("Titus",            ["tit", "ti"]),
    ("Philemon",         ["phlm", "phm"]),
    ("Hebrews",          ["heb", "he"]),
    ("James",            ["jas", "jm"]),
    ("1 Peter",          ["1pet", "1pe", "1pt", "1 pet", "1peter"]),
    ("2 Peter",          ["2pet", "2pe", "2pt", "2 pet", "2peter"]),
    ("1 John",           ["1john", "1jn", "1jo", "1 john", "1 jn"]),
    ("2 John",           ["2john", "2jn", "2jo", "2 john", "2 jn"]),
    ("3 John",           ["3john", "3jn", "3jo", "3 john", "3 jn"]),
    ("Jude",             ["jude", "jd"]),
    ("Revelation",       ["rev", "re", "rv", "apoc"]),
]

# Build the lookup dict (lowercase alias → canonical)
BOOK_ALIASES: dict[str, str] = {}
for _canonical, _aliases in _ALIAS_PAIRS:
    BOOK_ALIASES[_canonical.lower()] = _canonical
    for _a in _aliases:
        BOOK_ALIASES[_a.lower()] = _canonical


def normalize_book(token: str) -> str | None:
    """Map a book token to its canonical name.

    Handles forms like '1Cor', 'LK13', '1Thes'.
    Returns None if unrecognized.
    """
    if not token:
        return None

    # Strip trailing digits (chapter merged into book token, e.g. "LK13")
    stripped = re.sub(r'\d+.*$', '', token.strip()).strip()
    key = stripped.lower()
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]

    # Try with the digits as prefix (e.g. "1Cor" → "1cor")
    key2 = token.strip().lower()
    if key2 in BOOK_ALIASES:
        return BOOK_ALIASES[key2]

    # Attempt prefix match for very short unique abbreviations
    matches = [v for k, v in BOOK_ALIASES.items() if k.startswith(key) and len(key) >= 2]
    unique = list(dict.fromkeys(matches))  # deduplicate keeping order
    if len(unique) == 1:
        return unique[0]

    return None


# ---------------------------------------------------------------------------
# Reference parser
# ---------------------------------------------------------------------------
# Regex to capture: book token, chapter, verse start, optional verse end
# Handles separators: _ : v  (chapter:verse boundary)
# Handles F/FF suffix (verse-forward)
_REF_RE = re.compile(
    r'^'
    r'(?P<book>[1-3]?\s*[A-Za-z]+)'     # book (may start with digit)
    r'\s*'
    r'(?P<chapter>\d+)'                  # chapter number
    r'[_:v]'                             # separator
    r'(?P<verse_start>\d+)'              # verse start
    r'(?:-(?P<verse_end>\d+))?'          # optional -end
    r'(?P<suffix>[Ff]{1,2})?'            # optional F/FF
    r'.*$',
    re.IGNORECASE,
)


def parse_reference(raw: str) -> str | None:
    """Parse a scripture reference string into canonical form.

    Examples:
        '1 Cor 7_1-5'  → '1 Corinthians 7:1-5'
        'LK13_6F'       → 'Luke 13:6'
        'Ps 23'         → 'Psalms 23'
    """
    if not raw:
        return None

    raw = raw.strip()

    # Try full chapter:verse pattern first
    m = _REF_RE.match(raw)
    if m:
        book_tok = m.group('book').strip()
        canonical = normalize_book(book_tok)
        if canonical is None:
            return None
        chapter = m.group('chapter')
        verse_start = m.group('verse_start')
        verse_end = m.group('verse_end')
        ref = f"{canonical} {chapter}:{verse_start}"
        if verse_end:
            ref += f"-{verse_end}"
        return ref

    # Try book + chapter only (no verse separator)
    m2 = re.match(r'^(?P<book>[1-3]?\s*[A-Za-z]+)\s*(?P<chapter>\d+)$', raw.strip())
    if m2:
        canonical = normalize_book(m2.group('book').strip())
        if canonical:
            return f"{canonical} {m2.group('chapter')}"

    # Try book only
    canonical = normalize_book(raw.strip())
    if canonical:
        return canonical

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Normalize Bible scripture references.')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--ref',   metavar='TEXT', help='Parse a single reference')
    group.add_argument('--list',  action='store_true', help='Dump all canonical book names')
    group.add_argument('--audit', metavar='PATH',
                       help='Parse all filenames in a directory and report unrecognized refs')
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        for b in CANONICAL_BOOKS:
            print(b)
        return

    if args.ref:
        result = parse_reference(args.ref)
        print(result if result else f"(unrecognized: {args.ref!r})")
        return

    # --audit mode
    root = Path(args.audit)
    if not root.is_dir():
        print(f"ERROR: {args.audit} is not a directory", file=sys.stderr)
        sys.exit(1)

    unrecognized = []
    for entry in sorted(root.iterdir()):
        if entry.is_file():
            stem = entry.stem
            ref = parse_reference(stem)
            if ref:
                print(f"OK  {stem!r:60s} → {ref}")
            else:
                unrecognized.append(stem)

    if unrecognized:
        print(f"\n--- Unrecognized ({len(unrecognized)}) ---")
        for s in unrecognized:
            print(f"  {s!r}")


if __name__ == '__main__':
    main()
