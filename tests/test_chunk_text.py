"""Tests for build/chunk_text.py — sentence splitting and sliding-window chunker."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build.chunk_text import split_sentences, chunk_document, word_count


# ---------------------------------------------------------------------------
# word_count
# ---------------------------------------------------------------------------

def test_word_count_basic():
    assert word_count("hello world") == 2


def test_word_count_empty():
    assert word_count("") == 0


def test_word_count_extra_spaces():
    assert word_count("  one  two  three  ") == 3


# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------

def test_split_sentences_basic():
    text = "Jesus spoke to the crowd. He said, 'Follow me.'"
    sents = split_sentences(text)
    assert len(sents) >= 1
    assert any('Jesus' in s for s in sents)


def test_split_sentences_paragraph_boundary():
    text = "First paragraph sentence.\n\nSecond paragraph sentence."
    sents = split_sentences(text)
    assert len(sents) == 2


def test_split_sentences_abbreviation_protection():
    # "Dr." and "Rev." should NOT split the sentence
    text = "Dr. Smith spoke. Rev. Jones replied."
    sents = split_sentences(text)
    # Both sentences should be in the output; "Dr." should not create an extra split
    assert len(sents) == 2
    assert any('Dr.' in s for s in sents)
    assert any('Rev.' in s for s in sents)


def test_split_sentences_empty():
    assert split_sentences("") == []


def test_split_sentences_no_sentence_end():
    text = "This is a sentence with no ending punctuation"
    sents = split_sentences(text)
    assert len(sents) == 1
    assert sents[0] == text


# ---------------------------------------------------------------------------
# chunk_document
# ---------------------------------------------------------------------------

SERMON_TEXT = (
    "The grace of God is foundational to all Christian teaching. "
    "Without grace, salvation would be impossible for any human being. "
    "Scripture tells us clearly that we are saved by grace through faith. "
    "This is not of ourselves; it is the gift of God. "
    "No one can boast before the Lord about their own righteousness. "
    "The apostle Paul wrote extensively about this glorious truth. "
    "He proclaimed that Christ died for sinners while they were yet enemies of God. "
    "This demonstrates the depth and breadth of divine love beyond all measure. "
    "We should respond to such grace with gratitude, worship, and obedience. "
    "Every sermon should ultimately lead us back to the cross of Christ Jesus. "
    "The resurrection confirms that the sacrifice was accepted by the Father. "
    "Eternal life is the gift granted to all who believe in His name. "
) * 3  # repeat to ensure we get multiple chunks


def test_chunk_document_returns_list():
    chunks = chunk_document(SERMON_TEXT, target_words=100, min_words=30)
    assert isinstance(chunks, list)


def test_chunk_document_non_empty():
    chunks = chunk_document(SERMON_TEXT, target_words=100, min_words=30)
    assert len(chunks) >= 2, "Long text should produce multiple chunks"


def test_chunk_document_min_words_respected():
    chunks = chunk_document(SERMON_TEXT, target_words=100, min_words=30)
    for c in chunks:
        assert word_count(c) >= 30, f"Chunk shorter than min_words: {word_count(c)}"


def test_chunk_document_empty_text():
    assert chunk_document("") == []


def test_chunk_document_short_text_below_min():
    # A 10-word text with min=50 should return nothing
    short = "Jesus loves us all very much indeed today."
    chunks = chunk_document(short, target_words=100, min_words=50)
    assert chunks == []


def test_chunk_document_no_consecutive_duplicates():
    chunks = chunk_document(SERMON_TEXT, target_words=100, min_words=30)
    for i in range(len(chunks) - 1):
        assert chunks[i] != chunks[i + 1], "Consecutive duplicate chunks detected"
