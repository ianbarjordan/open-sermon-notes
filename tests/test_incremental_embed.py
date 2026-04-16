"""Tests for 02_chunk_embed.py — incremental indexing logic.

Uses in-memory FAISS and SQLite to avoid touching real data/artifacts.
"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load 02_chunk_embed.py via importlib (numeric prefix workaround)
_spec = importlib.util.spec_from_file_location(
    "chunk_embed02",
    str(Path(__file__).resolve().parent.parent / "build" / "02_chunk_embed.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

init_db               = _mod.init_db
insert_chunk_fts      = _mod.insert_chunk_fts
insert_document_metadata = _mod.insert_document_metadata
build_index_incremental  = _mod.build_index_incremental
save_artifacts           = _mod.save_artifacts
load_documents           = _mod.load_documents

# Try to import faiss — skip incremental tests if not available
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


DIM = 384


def _make_index(n_vectors: int = 0) -> 'faiss.IndexFlatL2':
    index = faiss.IndexFlatL2(DIM)
    if n_vectors:
        vecs = np.random.rand(n_vectors, DIM).astype('float32')
        index.add(vecs)
    return index


def _make_doc(doc_id: str) -> dict:
    return {
        'doc_id':        doc_id,
        'sha256':        f'hash_{doc_id}',
        'source_file':   f'SampleData/{doc_id}.docx',
        'title':         f'Sermon {doc_id}',
        'scripture_ref': 'John 3:16',
        'date':          '2024-01-01',
        'format':        'ooxml_doc',
        'word_count':    200,
        'text': (
            'The grace of God is foundational. '
            'Jesus Christ died for our sins on the cross. '
            'Scripture teaches us about forgiveness and salvation. '
            'We are saved by faith through grace. '
        ) * 5,
    }


class _MockModel:
    """Fake SentenceTransformer that returns random normalized vectors."""
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        vecs = np.random.rand(len(texts), DIM).astype('float32')
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            vecs = vecs / (norms + 1e-9)
        return vecs


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = init_db(db_path)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' OR type='shadow'"
            ).fetchall()
        }
        assert 'documents' in tables
        conn.close()


def test_init_db_force_drops_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = init_db(db_path)
        conn.execute("INSERT INTO documents (doc_id, sha256, source_file) VALUES ('x','h','y')")
        conn.commit()
        conn.close()

        conn2 = init_db(db_path, force=True)
        count = conn2.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 0
        conn2.close()


# ---------------------------------------------------------------------------
# save_artifacts / load round-trip
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FAISS_AVAILABLE, reason="faiss not installed")
def test_save_artifacts_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        faiss_path = str(Path(tmpdir) / "test.faiss")
        idmap_path = str(Path(tmpdir) / "id_map.json")
        index = _make_index(5)
        id_map = {0: 'a::0', 1: 'a::1', 2: 'b::0', 3: 'b::1', 4: 'c::0'}

        save_artifacts(index, id_map, faiss_path, idmap_path)

        loaded = faiss.read_index(faiss_path)
        assert loaded.ntotal == 5

        with open(idmap_path) as f:
            raw = json.load(f)
        loaded_map = {int(k): v for k, v in raw.items()}
        assert loaded_map == id_map


# ---------------------------------------------------------------------------
# build_index_incremental
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FAISS_AVAILABLE, reason="faiss not installed")
def test_incremental_adds_new_docs():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = init_db(db_path)

        # Seed the DB with one doc
        existing_doc = _make_doc('existing_doc')
        insert_document_metadata(conn, existing_doc)
        for i, txt in enumerate(existing_doc['text'].split('. ')[:3]):
            if txt.strip():
                insert_chunk_fts(conn, f"existing_doc::{i}", existing_doc, txt)
        conn.commit()

        existing_index = _make_index(3)
        existing_id_map = {0: 'existing_doc::0', 1: 'existing_doc::1', 2: 'existing_doc::2'}

        new_doc = _make_doc('new_doc')
        model = _MockModel()

        updated_index, updated_id_map = build_index_incremental(
            [new_doc], [], model, conn, existing_index, existing_id_map, batch_size=8
        )

        # FAISS should have more vectors than before
        assert updated_index.ntotal > 3

        # New doc should be in the DB
        row = conn.execute(
            "SELECT doc_id FROM documents WHERE doc_id = 'new_doc'"
        ).fetchone()
        assert row is not None

        conn.close()


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="faiss not installed")
def test_incremental_no_new_docs_is_noop():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = init_db(db_path)

        existing_index = _make_index(0)
        existing_id_map = {}
        model = _MockModel()

        # Pass empty new_docs list
        updated_index, updated_id_map = build_index_incremental(
            [], [], model, conn, existing_index, existing_id_map, batch_size=8
        )

        assert updated_index.ntotal == 0
        assert updated_id_map == {}
        conn.close()


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="faiss not installed")
def test_incremental_id_map_offset():
    """New chunk ids in id_map should start at offset == existing_index.ntotal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = init_db(db_path)

        offset = 7
        existing_index = _make_index(offset)
        existing_id_map = {i: f'old_doc::{i}' for i in range(offset)}

        new_doc = _make_doc('fresh_doc')
        model = _MockModel()

        _, updated_id_map = build_index_incremental(
            [new_doc], [], model, conn, existing_index, existing_id_map, batch_size=8
        )

        new_keys = [k for k in updated_id_map if k >= offset]
        assert len(new_keys) > 0, "New entries should be added at offset"
        for k in new_keys:
            assert updated_id_map[k].startswith('fresh_doc::')

        conn.close()


# ---------------------------------------------------------------------------
# load_documents
# ---------------------------------------------------------------------------

def test_load_documents_reads_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        doc = _make_doc('test_load')
        p = Path(tmpdir) / "test_load.json"
        p.write_text(json.dumps(doc))

        docs = load_documents(tmpdir)
        assert len(docs) == 1
        assert docs[0]['doc_id'] == 'test_load'


def test_load_documents_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        docs = load_documents(tmpdir)
        assert docs == []
