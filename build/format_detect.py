"""
format_detect.py — Read magic bytes to determine true file format.

Usage:
    python build/format_detect.py --file path/to/file
    python build/format_detect.py --dir SampleData/ --verbose
"""
import argparse
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Magic byte signatures
# ---------------------------------------------------------------------------
MAGIC_OLE2   = b'\xd0\xcf\x11\xe0'   # OLE2 compound document
MAGIC_RTF    = b'{\\'                  # Rich Text Format
MAGIC_OOXML  = b'PK\x03\x04'          # ZIP / OOXML container


def detect_format(path: str) -> str:
    """Return 'ole2', 'rtf', 'ooxml', or 'unknown' based on magic bytes."""
    try:
        with open(path, 'rb') as fh:
            header = fh.read(8)
    except OSError:
        return 'unknown'

    if header[:4] == MAGIC_OLE2:
        return 'ole2'
    if header[:2] == MAGIC_RTF:
        return 'rtf'
    if header[:4] == MAGIC_OOXML:
        return 'ooxml'
    return 'unknown'


def classify_ole2(path: str) -> str:
    """Return 'ole2_pub' or 'ole2_word'.

    Fast path: .pub extension → 'ole2_pub'.
    Otherwise assume Word.
    """
    if Path(path).suffix.lower() == '.pub':
        return 'ole2_pub'
    return 'ole2_word'


def probe_file(path: str, verbose: bool = False) -> dict:
    """Return a dict with path, format, and (for ole2) subtype."""
    fmt = detect_format(path)
    result = {'path': path, 'format': fmt}
    if fmt == 'ole2':
        result['subtype'] = classify_ole2(path)
    if verbose:
        subtype = result.get('subtype', '')
        print(f"{path}: {fmt}" + (f" ({subtype})" if subtype else ""))
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='Probe file format via magic bytes.'
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--file', metavar='PATH', help='Probe a single file')
    group.add_argument('--dir',  metavar='PATH', help='Probe all files in a directory')
    p.add_argument('--verbose', action='store_true', help='Print per-file decisions')
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.file:
        result = probe_file(args.file, verbose=True)
        sys.exit(0)

    # --dir mode
    root = Path(args.dir)
    if not root.is_dir():
        print(f"ERROR: {args.dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    counts: dict[str, int] = {}
    for entry in sorted(root.iterdir()):
        if entry.is_file():
            r = probe_file(str(entry), verbose=args.verbose)
            fmt = r.get('subtype', r['format'])
            counts[fmt] = counts.get(fmt, 0) + 1

    print("\n--- Summary ---")
    for fmt, n in sorted(counts.items()):
        print(f"  {fmt:20s} {n}")


if __name__ == '__main__':
    main()
