"""
chunk_text.py — Sentence-aware sliding window chunker (no NLTK/spaCy).

Usage:
    python build/chunk_text.py --text path/to/file.txt --count
    python build/chunk_text.py --text path/to/file.txt --target 150 --min 50
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import COMMENTARY_CHUNK_WORDS, MIN_CHUNK_WORDS  # noqa: E402

# ---------------------------------------------------------------------------
# Common sermon/biblical abbreviations whose periods should not split sentences.
# Strategy: protect them before splitting, then restore.
# ---------------------------------------------------------------------------
_ABBREVS = [
    'Rev', 'vs', 'cf', 'e.g', 'i.e', 'etc',
    'Dr', 'Mr', 'Mrs', 'Ms', 'Prof', 'Sr', 'Jr',
    'Gen', 'Ex', 'Lev', 'Num', 'Deut', 'Josh', 'Ps',
    'Psa', 'Prov', 'Eccl', 'Isa', 'Jer', 'Ezek', 'Dan',
    'Matt', 'Lk', 'Jn', 'Rom', 'Cor', 'Gal', 'Eph',
    'Phil', 'Col', 'Thess', 'Tim', 'Heb', 'Jas', 'Pet',
    'No', 'Vol', 'pp',
]
# Placeholder that won't appear in normal text
_PERIOD_PLACEHOLDER = '\x00DOT\x00'

# Sentence-ending regex: [.!?] followed by whitespace + capital or open-quote
_SENTENCE_SPLIT_RE = re.compile(r'([.!?])\s+(?=[A-Z\u201c\u2018"])')


def word_count(text: str) -> int:
    """Count words by whitespace split."""
    return len(text.split())


def _protect_abbrevs(text: str) -> str:
    """Replace periods in known abbreviations with a placeholder."""
    for abbrev in _ABBREVS:
        # Match abbreviation followed by a period (case-sensitive)
        pattern = re.escape(abbrev) + r'\.'
        text = re.sub(pattern, abbrev + _PERIOD_PLACEHOLDER, text)
    return text


def _restore_abbrevs(text: str) -> str:
    return text.replace(_PERIOD_PLACEHOLDER, '.')


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using a regex approach.

    Handles common sermon abbreviations to avoid false splits.
    """
    # Normalize line endings and collapse excessive blank lines
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Split on paragraph boundaries first (double newlines)
    paragraphs = re.split(r'\n\n+', text)
    sentences: list[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Replace single newlines with spaces within a paragraph
        para = re.sub(r'\n', ' ', para)
        para = re.sub(r'\s+', ' ', para)

        # Protect abbreviation periods before splitting
        protected = _protect_abbrevs(para)

        # Split into sentences within paragraph
        parts = _SENTENCE_SPLIT_RE.split(protected)
        # _SENTENCE_SPLIT_RE captures the punctuation char → [sent, '.', sent, ...]
        # Recombine: pair each sentence fragment with its trailing punctuation
        combined: list[str] = []
        i = 0
        while i < len(parts):
            frag = parts[i]
            if i + 1 < len(parts) and parts[i + 1] in '.!?':
                frag = frag + parts[i + 1]
                i += 2
            else:
                i += 1
            frag = _restore_abbrevs(frag).strip()
            if frag:
                combined.append(frag)

        sentences.extend(combined)

    return [s for s in sentences if s.strip()]


def chunk_document(
    text: str,
    target_words: int = COMMENTARY_CHUNK_WORDS,
    min_words: int = MIN_CHUNK_WORDS,
    overlap_ratio: float = 0.5,
) -> list[str]:
    """Return a list of overlapping chunk strings.

    Algorithm:
    1. Split text into sentences.
    2. Accumulate sentences into a window until word count >= target_words.
    3. Emit the window as a chunk.
    4. Slide forward dropping sentences from the start until the window is
       < overlap_ratio * target_words words.
    5. Discard final chunks with < min_words words.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    window: list[str] = []
    window_wc = 0

    overlap_threshold = int(target_words * overlap_ratio)

    for sent in sentences:
        sw = word_count(sent)
        window.append(sent)
        window_wc += sw

        if window_wc >= target_words:
            chunk_text = ' '.join(window)
            if word_count(chunk_text) >= min_words:
                chunks.append(chunk_text)

            # Slide: drop sentences from front until below overlap threshold
            while window_wc > overlap_threshold and len(window) > 1:
                removed = window.pop(0)
                window_wc -= word_count(removed)

    # Emit remaining window as final chunk
    if window:
        final = ' '.join(window)
        if word_count(final) >= min_words:
            chunks.append(final)

    # Deduplicate consecutive identical chunks (edge case)
    deduped: list[str] = []
    for c in chunks:
        if not deduped or c != deduped[-1]:
            deduped.append(c)

    return deduped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Sentence-aware sliding window chunker.')
    p.add_argument('--text',    metavar='PATH',  required=True, help='Input text file')
    p.add_argument('--target',  metavar='INT',   type=int, default=COMMENTARY_CHUNK_WORDS,
                   help=f'Target chunk word count (default: {COMMENTARY_CHUNK_WORDS})')
    p.add_argument('--min',     metavar='INT',   type=int, default=MIN_CHUNK_WORDS,
                   help=f'Minimum chunk word count (default: {MIN_CHUNK_WORDS})')
    p.add_argument('--overlap', metavar='FLOAT', type=float, default=0.5,
                   help='Overlap ratio (default: 0.5)')
    p.add_argument('--count',   action='store_true', help='Print chunk count only')
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    text_path = Path(args.text)
    if not text_path.is_file():
        print(f"ERROR: {args.text} not found", file=sys.stderr)
        sys.exit(1)

    text = text_path.read_text(encoding='utf-8', errors='replace')
    chunks = chunk_document(text, args.target, args.min, args.overlap)

    if args.count:
        print(f"Chunks: {len(chunks)}")
        return

    for i, chunk in enumerate(chunks):
        wc = word_count(chunk)
        print(f"--- Chunk {i} ({wc} words) ---")
        print(chunk)
        print()


if __name__ == '__main__':
    main()
