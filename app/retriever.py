"""
retriever.py — Load FAISS + SQLite at startup; hybrid dense+sparse retrieval.

Usage:
    python app/retriever.py --query "What did I preach about forgiveness?"
    python app/retriever.py --query "zzxyzzy gibberish"
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import (  # noqa: E402
    CONFIDENCE_THRESHOLD,
    DB_PATH,
    EMBED_MODEL,
    EMBED_QUERY_PREFIX,
    EMBEDDING_DIM,
    FAISS_PATH,
    ID_MAP_PATH,
    RRF_K,
    SERMON_ROOT,
    TOP_K,
)


# ---------------------------------------------------------------------------
# FTS5 query sanitizer
# ---------------------------------------------------------------------------

def sanitize_fts_query(query: str) -> str:
    """Convert a free-text query into a safe FTS5 MATCH expression."""
    cleaned = re.sub(r'["*^()\-+]', ' ', query)
    tokens = [t for t in cleaned.split() if len(t) >= 3]
    if not tokens:
        return '""'
    return ' OR '.join(f'"{t}"' for t in tokens)


# ---------------------------------------------------------------------------
# Retriever class
# ---------------------------------------------------------------------------

class Retriever:
    def __init__(
        self,
        index,        # faiss.IndexFlatL2
        id_map: dict, # {int_pos: chunk_id}
        conn: sqlite3.Connection,
        model,        # SentenceTransformer
        sermon_root: str = SERMON_ROOT,
    ):
        self._index = index
        self._id_map = id_map
        self._conn = conn
        self._model = model
        self.sermon_root = sermon_root

    # ------------------------------------------------------------------
    def dense_search(self, query: str, top_k: int = TOP_K * 3) -> list[dict]:
        """Embed query (with EMBED_QUERY_PREFIX) and search FAISS."""
        import numpy as np
        prefixed = EMBED_QUERY_PREFIX + query
        vec = self._model.encode([prefixed], normalize_embeddings=True)
        vec = vec.astype('float32')

        n = min(top_k, self._index.ntotal)
        if n == 0:
            return []

        distances, indices = self._index.search(vec, n)
        hits = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            chunk_id = self._id_map.get(int(idx))
            if chunk_id is None:
                continue
            hits.append({'chunk_id': chunk_id, 'l2_dist': float(dist)})
        return hits

    # ------------------------------------------------------------------
    def sparse_search(self, query: str, top_k: int = TOP_K * 3) -> list[dict]:
        """FTS5 MATCH query → BM25-ranked hits."""
        fts_query = sanitize_fts_query(query)
        try:
            rows = self._conn.execute(
                """
                SELECT chunk_id, doc_id, title, scripture_ref, date, source_file, text
                FROM chunks
                WHERE chunks MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        hits = []
        for row in rows:
            rel_path = row[5] or ''
            # Resolve relative path using the instance's sermon_root
            abs_path = str((Path(self.sermon_root) / rel_path).resolve()) if rel_path else ''
            hits.append({
                'chunk_id':     row[0],
                'doc_id':       row[1],
                'title':        row[2],
                'scripture_ref': row[3],
                'date':         row[4],
                'source_file':  abs_path,
                'text':         row[6],
            })
        return hits

    # ------------------------------------------------------------------
    def rrf_fuse(
        self,
        dense_hits: list[dict],
        sparse_hits: list[dict],
        k: int = RRF_K,
    ) -> list[tuple[str, float]]:
        """Reciprocal Rank Fusion: score = sum(1/(k + rank + 1))."""
        scores: dict[str, float] = {}
        for rank, hit in enumerate(dense_hits):
            cid = hit['chunk_id']
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        for rank, hit in enumerate(sparse_hits):
            cid = hit['chunk_id']
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: -x[1])

    # ------------------------------------------------------------------
    def fetch_chunks(
        self,
        chunk_ids: list[str],
        min_score: float = CONFIDENCE_THRESHOLD,
        scores: dict | None = None,
    ) -> list[dict]:
        """Fetch full chunk records from FTS5 by chunk_id list."""
        if not chunk_ids:
            return []

        placeholders = ','.join('?' * len(chunk_ids))
        rows = self._conn.execute(
            f"""
            SELECT chunk_id, doc_id, title, scripture_ref, date, source_file, text
            FROM chunks
            WHERE chunk_id IN ({placeholders})
            """,
            chunk_ids,
        ).fetchall()

        # Build lookup
        row_map = {row[0]: row for row in rows}

        results = []
        for cid in chunk_ids:
            row = row_map.get(cid)
            if row is None:
                continue
            score = (scores or {}).get(cid, 0.0)
            if score < min_score:
                continue
            rel_path = row[5] or ''
            abs_path = str((Path(self.sermon_root) / rel_path).resolve()) if rel_path else ''

            results.append({
                'chunk_id':     row[0],
                'doc_id':       row[1],
                'title':        row[2],
                'scripture_ref': row[3],
                'date':         row[4],
                'source_file':  abs_path,
                'text':         row[6],
                'score':        score,
            })
        return results

    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Full hybrid search: dense → sparse → RRF → fetch → top_k."""
        dense = self.dense_search(query, top_k=top_k * 3)
        sparse = self.sparse_search(query, top_k=top_k * 3)
        fused = self.rrf_fuse(dense, sparse)

        # Keep top candidates (before confidence filter)
        top_ids = [cid for cid, _ in fused[:top_k * 2]]
        score_map = {cid: score for cid, score in fused}

        chunks = self.fetch_chunks(top_ids, min_score=CONFIDENCE_THRESHOLD, scores=score_map)
        return chunks[:top_k]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def load_retriever(
    db_path: str = DB_PATH,
    faiss_path: str = FAISS_PATH,
    idmap_path: str = ID_MAP_PATH,
    model_name: str = EMBED_MODEL,
) -> Retriever:
    """Load all artifacts and return a ready Retriever. Called once at startup."""
    import faiss
    from sentence_transformers import SentenceTransformer

    index = faiss.read_index(faiss_path)
    print(f"Loaded FAISS index: {index.ntotal} vectors from {faiss_path!r}")

    with open(idmap_path, encoding='utf-8') as fh:
        raw_map = json.load(fh)
    id_map = {int(k): v for k, v in raw_map.items()}
    print(f"Loaded id_map: {len(id_map)} entries")

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")

    model = SentenceTransformer(model_name)
    print(f"Loaded embedding model: {model_name!r}")

    return Retriever(index=index, id_map=id_map, conn=conn, model=model)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Hybrid retriever for sermon chunks.')
    p.add_argument('--query',  metavar='TEXT', required=True, help='Search query')
    p.add_argument('--db',     metavar='PATH', default=DB_PATH)
    p.add_argument('--faiss',  metavar='PATH', default=FAISS_PATH)
    p.add_argument('--idmap',  metavar='PATH', default=ID_MAP_PATH)
    p.add_argument('--top-k',  metavar='INT',  type=int, default=TOP_K)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    retriever = load_retriever(
        db_path=args.db,
        faiss_path=args.faiss,
        idmap_path=args.idmap,
    )
    results = retriever.search(args.query, top_k=args.top_k)
    if not results:
        print("No results found.")
        return

    for i, chunk in enumerate(results):
        print(f"\n[{i+1}] {chunk.get('title', '(no title)')} "
              f"({chunk.get('scripture_ref', '')}) — {chunk.get('date', '')}")
        print(f"  Source: {chunk.get('source_file', '')}")
        print(f"  Score:  {chunk.get('score', 0):.4f}")
        print(f"  {chunk['text'][:200]}...")


if __name__ == '__main__':
    main()
