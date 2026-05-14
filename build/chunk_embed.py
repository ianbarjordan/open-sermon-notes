"""
chunk_embed.py — Read JSON docs → chunk → embed with BGE-small →
write FAISS IndexFlatL2 + SQLite FTS5 + id_map.json.

Usage:
    python build/chunk_embed.py --dry-run
    python build/chunk_embed.py
    python build/chunk_embed.py --force
    python build/chunk_embed.py --incremental
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import (  # noqa: E402
    COMMENTARY_CHUNK_WORDS,
    DB_PATH,
    DOCUMENTS_DIR,
    EMBED_MODEL,
    FAISS_PATH,
    ID_MAP_PATH,
    MIN_CHUNK_WORDS,
)
from build.chunk_text import chunk_document  # noqa: E402

# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------

def load_documents(docs_dir: str) -> list[dict]:
    """Load all JSON documents from the documents directory."""
    docs = []
    for p in sorted(Path(docs_dir).glob('*.json')):
        try:
            with open(p, encoding='utf-8') as fh:
                docs.append(json.load(fh))
        except Exception as e:
            print(f"WARNING: could not load {p}: {e}", file=sys.stderr)
    return docs


def load_documents_from_db(db_path: str) -> list[dict]:
    """Load all documents from the SQLite documents table.

    Used when data/documents/ JSON files are absent — e.g. when running
    from a pre-built search bundle that ships without the intermediate JSON
    staging files.  Returns the same dict shape as load_documents().
    """
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT doc_id, sha256, source_file, title, scripture_ref,
                   date, format, word_count, text
            FROM documents
            """
        ).fetchall()
    except sqlite3.OperationalError:
        # documents table doesn't exist yet (fresh DB)
        return []
    finally:
        conn.close()
    cols = ['doc_id', 'sha256', 'source_file', 'title',
            'scripture_ref', 'date', 'format', 'word_count', 'text']
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# SQLite setup
# ---------------------------------------------------------------------------

_CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    title         TEXT,
    scripture_ref TEXT,
    date          TEXT,
    format        TEXT,
    word_count    INTEGER,
    text          TEXT,
    ingested_at   TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_CHUNKS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    chunk_id    UNINDEXED,
    doc_id      UNINDEXED,
    title,
    scripture_ref,
    date        UNINDEXED,
    source_file UNINDEXED,
    text,
    tokenize = 'porter ascii'
);
"""


def init_db(db_path: str, force: bool = False) -> sqlite3.Connection:
    """Create or open the SQLite database in WAL mode."""
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    if force and db_file.exists():
        db_file.unlink()
        print(f"Dropped existing database: {db_path}")

    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_CREATE_DOCUMENTS)
    conn.executescript(_CREATE_CHUNKS)
    conn.commit()
    return conn


def insert_document_metadata(conn: sqlite3.Connection, doc: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO documents
            (doc_id, sha256, source_file, title, scripture_ref, date, format, word_count, text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc['doc_id'],
            doc.get('sha256', 'legacy_no_hash'),
            doc['source_file'],
            doc.get('title'),
            doc.get('scripture_ref'),
            doc.get('date'),
            doc.get('format'),
            doc.get('word_count'),
            doc.get('text', ''),
        ),
    )


def insert_chunk_fts(
    conn: sqlite3.Connection,
    chunk_id: str,
    doc: dict,
    text: str,
) -> None:
    conn.execute(
        """
        INSERT INTO chunks (chunk_id, doc_id, title, scripture_ref, date, source_file, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            doc['doc_id'],
            doc.get('title') or '',
            doc.get('scripture_ref') or '',
            doc.get('date') or '',
            doc.get('source_file') or '',
            text,
        ),
    )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_chunks(texts: list[str], model, batch_size: int = 64):
    """Embed a list of texts, returning a float32 numpy array (N, D)."""
    import numpy as np
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_vecs.append(vecs)
    return np.vstack(all_vecs).astype('float32')


# ---------------------------------------------------------------------------
# Core build
# ---------------------------------------------------------------------------

def build_index(docs: list[dict], model, conn: sqlite3.Connection, batch_size: int,
                progress: bool = True):
    """Chunk, embed, insert into FTS5, return (faiss_index, id_map).

    progress=False suppresses tqdm — used when stdout is captured in-process.
    """
    import faiss
    import numpy as np

    all_texts: list[str] = []
    all_chunk_ids: list[str] = []
    chunk_docs: list[dict] = []  # parallel to all_texts

    print(f"Chunking {len(docs)} documents...")
    for doc in docs:
        text = doc.get('text', '')
        if not text:
            continue
        chunks = chunk_document(text, COMMENTARY_CHUNK_WORDS, MIN_CHUNK_WORDS)
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{doc['doc_id']}::{idx}"
            all_texts.append(chunk)
            all_chunk_ids.append(chunk_id)
            chunk_docs.append(doc)

    print(f"Total chunks: {len(all_texts)}")

    if not all_texts:
        print("No chunks to embed.", file=sys.stderr)
        dim = model.get_sentence_embedding_dimension()
        index = faiss.IndexFlatL2(dim)
        return index, {}

    # Embed
    print(f"Embedding with {EMBED_MODEL} (batch={batch_size})...")
    bar = None
    if progress:
        try:
            from tqdm import tqdm
            bar = tqdm(total=len(all_texts), unit='chunk')
        except ImportError:
            pass

    import numpy as np
    all_vecs_list = []
    for i in range(0, len(all_texts), batch_size):
        batch = all_texts[i:i + batch_size]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_vecs_list.append(vecs)
        if bar:
            bar.update(len(batch))
    if bar:
        bar.close()

    embeddings = np.vstack(all_vecs_list).astype('float32')

    # Build FAISS index
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)
    print(f"FAISS index: {index.ntotal} vectors, dim={dim}")

    # Build id_map {int_pos → chunk_id}
    id_map = {i: chunk_id for i, chunk_id in enumerate(all_chunk_ids)}

    # Insert into SQLite
    print("Writing SQLite FTS5...")
    conn.execute("DELETE FROM chunks")  # clear before re-inserting
    conn.execute("DELETE FROM documents")
    seen_docs = set()
    for i, (chunk_id, chunk_text, doc) in enumerate(
        zip(all_chunk_ids, all_texts, chunk_docs)
    ):
        if doc['doc_id'] not in seen_docs:
            insert_document_metadata(conn, doc)
            seen_docs.add(doc['doc_id'])
        insert_chunk_fts(conn, chunk_id, doc, chunk_text)

    conn.commit()
    print(f"SQLite: {len(seen_docs)} documents, {len(all_texts)} chunks")

    return index, id_map


def _remove_stale_chunks(conn: sqlite3.Connection, doc_id: str, index, id_map: dict):
    """
    Remove chunks belonging to doc_id from FAISS (not easily possible with IndexFlatL2
    without rebuild) and SQLite.

    Since FAISS IndexFlatL2 doesn't support easy deletion by ID, 'incremental'
    updates that modify existing documents will currently result in ORPHANED VECTORS
    in FAISS unless we rebuild the index.

    For v2 beta, if a hash mismatch occurs, we'll delete from SQLite and warn
    the user that a Full Rebuild is recommended for optimal vector search.
    """
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    # Also remove from id_map (marks slots as stale)
    for pos, cid in list(id_map.items()):
        if cid.startswith(f"{doc_id}::"):
            del id_map[pos]


def build_index_incremental(
    new_docs: list[dict],
    stale_doc_ids: list[str],
    model,
    conn: sqlite3.Connection,
    existing_index,
    existing_id_map: dict,
    batch_size: int,
    progress: bool = True,
) -> tuple:
    """Append-only update: embed new_docs and add to existing FAISS + FTS5.

    If stale_doc_ids is provided, these are removed from SQLite before adding.
    progress=False suppresses tqdm (used when stdout is captured in-process).
    """
    import numpy as np

    id_map = dict(existing_id_map)

    if stale_doc_ids:
        print(f"Removing {len(stale_doc_ids)} stale documents from SQLite...")
        for did in stale_doc_ids:
            _remove_stale_chunks(conn, did, existing_index, id_map)

    offset = existing_index.ntotal
    all_texts: list[str] = []
    all_chunk_ids: list[str] = []
    chunk_docs: list[dict] = []

    print(f"Chunking {len(new_docs)} new/updated documents...")
    for doc in new_docs:
        text = doc.get('text', '')
        if not text:
            continue
        chunks = chunk_document(text, COMMENTARY_CHUNK_WORDS, MIN_CHUNK_WORDS)
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{doc['doc_id']}::{idx}"
            all_texts.append(chunk)
            all_chunk_ids.append(chunk_id)
            chunk_docs.append(doc)

    print(f"New chunks: {len(all_texts)}")

    if not all_texts:
        print("No new chunks to embed.")
        return existing_index, id_map

    print(f"Embedding with {EMBED_MODEL} (batch={batch_size})...")
    bar = None
    if progress:
        try:
            from tqdm import tqdm
            bar = tqdm(total=len(all_texts), unit='chunk')
        except ImportError:
            pass

    all_vecs_list = []
    for i in range(0, len(all_texts), batch_size):
        batch = all_texts[i:i + batch_size]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_vecs_list.append(vecs)
        if bar:
            bar.update(len(batch))
    if bar:
        bar.close()

    embeddings = np.vstack(all_vecs_list).astype('float32')

    # Append to FAISS in-place
    existing_index.add(embeddings)
    print(f"FAISS index: {existing_index.ntotal} vectors total (+{len(all_texts)} new)")

    # Extend id_map
    for i, chunk_id in enumerate(all_chunk_ids):
        id_map[offset + i] = chunk_id

    # Insert into SQLite
    print("Writing new chunks to SQLite FTS5...")
    seen_docs: set = set()
    for chunk_id, chunk_text, doc in zip(all_chunk_ids, all_texts, chunk_docs):
        if doc['doc_id'] not in seen_docs:
            insert_document_metadata(conn, doc)
            seen_docs.add(doc['doc_id'])
        insert_chunk_fts(conn, chunk_id, doc, chunk_text)

    conn.commit()
    print(f"SQLite: +{len(seen_docs)} docs (new/updated), +{len(all_texts)} new chunks")

    return existing_index, id_map


def save_artifacts(index, id_map: dict, faiss_path: str, idmap_path: str) -> None:
    """Save FAISS index and id_map JSON."""
    import faiss
    Path(faiss_path).parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, faiss_path)
    print(f"Saved FAISS index: {faiss_path}")

    Path(idmap_path).parent.mkdir(parents=True, exist_ok=True)
    # Keys must be strings in JSON
    with open(idmap_path, 'w', encoding='utf-8') as fh:
        json.dump({str(k): v for k, v in id_map.items()}, fh)
    print(f"Saved id_map: {idmap_path} ({len(id_map)} entries)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Chunk + embed documents and build FAISS + FTS5 index.'
    )
    parser.add_argument('--docs',    metavar='PATH', default=DOCUMENTS_DIR,
                        help=f'JSON docs dir (default: {DOCUMENTS_DIR})')
    parser.add_argument('--db',      metavar='PATH', default=DB_PATH,
                        help=f'SQLite path (default: {DB_PATH})')
    parser.add_argument('--faiss',   metavar='PATH', default=FAISS_PATH,
                        help=f'FAISS path (default: {FAISS_PATH})')
    parser.add_argument('--idmap',   metavar='PATH', default=ID_MAP_PATH,
                        help=f'id_map JSON path (default: {ID_MAP_PATH})')
    parser.add_argument('--model',   metavar='STR',  default=EMBED_MODEL,
                        help=f'Embedding model (default: {EMBED_MODEL})')
    parser.add_argument('--batch',   metavar='INT',  type=int, default=64,
                        help='Batch size for embedding (default: 64)')
    parser.add_argument('--force',       action='store_true',
                        help='Drop and rebuild existing index')
    parser.add_argument('--dry-run',     action='store_true',
                        help='Chunk/count only, no writes')
    parser.add_argument('--incremental', action='store_true',
                        help='Append only new documents to existing index')
    parser.add_argument('--no-progress', action='store_true',
                        help='Suppress tqdm progress bars (in-process callers '
                             'should set this so a captured stdout buffer does '
                             'not fill with carriage-returned progress lines)')
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the chunk+embed pipeline. Caller passes a parsed Namespace.

    Returns 0 on success. All output goes to stdout — in-process callers
    should redirect sys.stdout before invoking.
    """
    docs = load_documents(args.docs)
    if not docs:
        print(f"No JSON docs found in {args.docs!r} — falling back to documents table in {args.db!r}")
        docs = load_documents_from_db(args.db)
    print(f"Loaded {len(docs)} documents")

    if args.dry_run:
        print("DRY RUN — counting chunks only, no index written")
        total_chunks = 0
        for doc in docs:
            text = doc.get('text', '')
            if text:
                chunks = chunk_document(text, COMMENTARY_CHUNK_WORDS, MIN_CHUNK_WORDS)
                total_chunks += len(chunks)
        print(f"Total chunks would be: {total_chunks}")
        return 0

    # Load embedding model
    print(f"Loading embedding model: {args.model}")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.model)

    if args.incremental:
        import faiss

        faiss_file = Path(args.faiss)
        idmap_file = Path(args.idmap)

        _progress = not getattr(args, 'no_progress', False)
        if not faiss_file.exists() or not idmap_file.exists():
            print("No existing index found — falling back to full build.")
            conn = init_db(args.db, force=False)
            index, id_map = build_index(docs, model, conn, args.batch, progress=_progress)
        else:
            # Load existing artifacts
            existing_index = faiss.read_index(str(faiss_file))
            with open(idmap_file, encoding='utf-8') as fh:
                raw = json.load(fh)
            existing_id_map = {int(k): v for k, v in raw.items()}

            conn = init_db(args.db, force=False)

            # Find doc_ids + hashes already in DB
            db_registry = {
                row[0]: row[1]
                for row in conn.execute("SELECT doc_id, sha256 FROM documents").fetchall()
            }
            
            new_docs = []
            stale_doc_ids = []
            
            for d in docs:
                did = d['doc_id']
                if did not in db_registry:
                    new_docs.append(d)
                elif d.get('sha256', '') != db_registry[did]:
                    new_docs.append(d)
                    stale_doc_ids.append(did)
            
            print(f"Already indexed: {len(db_registry)} docs.")
            print(f"New/Updated docs: {len(new_docs)} ({len(stale_doc_ids)} modified)")

            if stale_doc_ids:
                print(
                    f"NOTE: {len(stale_doc_ids)} modified doc(s) detected. "
                    "Their SQLite chunks will be replaced, but orphaned FAISS vectors "
                    "remain until a Full Rebuild is run. Search accuracy is unaffected "
                    "for new queries; run Full Rebuild to fully remove stale vectors."
                )

            if not new_docs:
                print("Index is already up to date. Nothing to add.")
                conn.close()
                return 0

            index, id_map = build_index_incremental(
                new_docs, stale_doc_ids, model, conn, existing_index, existing_id_map,
                args.batch, progress=_progress,
            )

        save_artifacts(index, id_map, args.faiss, args.idmap)
        conn.close()
        print("Done (incremental).")
        return 0

    # Full build (default)
    _progress = not getattr(args, 'no_progress', False)
    conn = init_db(args.db, force=args.force)
    index, id_map = build_index(docs, model, conn, args.batch, progress=_progress)
    save_artifacts(index, id_map, args.faiss, args.idmap)
    conn.close()
    print("Done.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. argv=None reads from sys.argv as usual."""
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
