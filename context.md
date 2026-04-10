# sermon-notes-offline — Project Context

Fully offline RAG desktop application for a pastor to query 27+ years of sermon notes.
Modelled on the wiki-offline architecture with key adaptations for sermon document types.

---

## Architecture Overview

```
raw/source_files/          ← original sermon files (gitignored)
       │
       ▼
build/01_ingest_files.py   ← parse + quarantine filter
       │
       ▼
build/02_chunk_embed.py    ← chunk text → embed with BGE-small → store in FAISS + FTS5
       │
       ▼
data/sermons.db            ← SQLite: FTS5 full-text index + chunk metadata
data/sermons.faiss         ← FAISS IVF index of 384-dim embeddings
data/id_map.json           ← maps FAISS integer IDs → chunk metadata keys
       │
       ▼
app/app.py                 ← Gradio UI: query → hybrid retrieval → Phi-3.5-mini LLM → answer
```

---

## Module Architecture

### Build Phase (`build/`)

| Script | Responsibility |
|--------|---------------|
| `01_ingest_files.py` | Walk `raw/source_files/`, detect format, parse to plain text, route failures to `raw/quarantine/` |
| `02_chunk_embed.py` | Split parsed text into chunks, embed with BGE-small-en-v1.5, write FAISS index + SQLite FTS5 |

**Helper modules (build/):**
- `normalize_scripture.py` — normalise Bible book names to canonical form (e.g. "Gen" → "Genesis")
- `parse_filename.py` — extract date, series, title metadata from filename
- `chunk_text.py` — sentence-aware chunking respecting `MIN_CHUNK_WORDS` / `COMMENTARY_CHUNK_WORDS`
- `format_detect.py` — distinguish OLE2 `.doc`, RTF masquerading as `.doc`, true `.docx`

### App Phase (`app/`)

| Script | Responsibility |
|--------|---------------|
| `app.py` | Gradio web UI, query entry point |
| `retriever.py` | Hybrid retrieval: FAISS ANN + FTS5 BM25, fused via RRF |
| `llm.py` | llama-cpp-python wrapper for Phi-3.5-mini-instruct |
| `config.py` | All constants and paths (single source of truth) |

---

## Data Flow

1. **Ingest:** `.docx`/`.pptx`/`.doc` files → plain text paragraphs
2. **Quarantine:** files failing quality checks → `raw/quarantine/<reason>/`
3. **Chunk:** text split into overlapping windows (~150 words for commentary)
4. **Embed:** BGE-small-en-v1.5 produces 384-dim vectors, stored in FAISS IVF
5. **Index:** SQLite FTS5 indexes raw chunk text for keyword search
6. **Query:** user question → embed (with query prefix) + BM25 search → RRF fusion → top-5 chunks → Phi-3.5-mini → answer

---

## Quarantine Categories

| Directory | Reason |
|-----------|--------|
| `format_pub/` | Microsoft Publisher files (`.pub`) — unreadable |
| `too_short/` | Parsed text below `MIN_CHUNK_WORDS` threshold |
| `filename_flagged/` | Filename suggests non-sermon content |
| `non_faith/` | Content classifier detects non-faith material |
| `sparse_pptx/` | PowerPoint with fewer than 3 text-bearing slides |
| `worship_slides/` | Lyrics-only slides with no sermon content |
| `duplicates/` | Near-duplicate of an already-indexed file |
| `manual_review/` | Ambiguous — needs human decision |

---

## Key Configuration (`app/config.py`)

| Constant | Value | Notes |
|----------|-------|-------|
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | 384-dim, ~33 MB |
| `EMBED_QUERY_PREFIX` | `"Represent this sentence..."` | Required for BGE asymmetric retrieval |
| `EMBEDDING_DIM` | `384` | Must match FAISS index dim |
| `MODEL_PATH` | `models/Phi-3.5-mini-instruct-Q4_K_M.gguf` | ~2.4 GB |
| `CTX_WINDOW` | `4096` | Phi-3.5-mini context |
| `TOP_K` | `5` | Chunks passed to LLM |
| `RRF_K` | `60` | RRF fusion constant |
| `NPROBE` | `64` | FAISS search probes |
| `CONFIDENCE_THRESHOLD` | `0.005` | Min RRF score (max ~0.033 with K=60) |
| `MIN_CHUNK_WORDS` | `50` | Discard very short chunks |
| `COMMENTARY_CHUNK_WORDS` | `150` | Target chunk size |

---

## Dependencies

### Build Phase
- `sentence-transformers>=3.0` — BGE embedding
- `faiss-cpu>=1.8` — vector index
- `python-docx>=1.1` — `.docx` parsing
- `python-pptx>=0.6` — `.pptx` parsing
- `numpy>=1.26`
- `tqdm>=4.66`

### App Phase
- `gradio>=5.0` — web UI
- `llama-cpp-python==0.3.16` — LLM inference
- `faiss-cpu>=1.8`
- `sentence-transformers>=3.0`
- `numpy>=1.26`

### System
- Python 3.11
- SQLite 3.35+ (FTS5 required — standard in Python 3.11)
- uv (virtual environment and package management)

---

## Entry Points

| Command | Purpose |
|---------|---------|
| `build/01_ingest_files.py --source raw/source_files/` | Parse and quarantine-filter all source files |
| `build/02_chunk_embed.py` | Build FAISS index and SQLite FTS5 database |
| `app/app.py` | Launch Gradio UI (http://localhost:7860) |

---

## Environment Setup

### Windows (native)

```powershell
# Prerequisites:
#   Python 3.11  — https://python.org/downloads
#   uv           — https://docs.astral.sh/uv/getting-started/installation/
#   Microsoft Word (required for .doc parsing via COM automation)

cd open-sermon-notes

# Create venv
uv venv .venv --python 3.11

# Activate
.venv\Scripts\activate

# Install torch (CPU build — sufficient for inference)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install build + app dependencies (pywin32 installed automatically on Windows)
pip install -r build/requirements_build.txt
pip install -r app/requirements_app.txt

# Run post-install step for pywin32 (registers COM components)
python .venv\Scripts\pywin32_postinstall.py -install
```

### Linux / WSL

```bash
cd sermon-notes-offline

# Prerequisites: antiword
sudo apt-get install -y antiword

uv venv .venv --python 3.11
uv pip install torch                          # CUDA build auto-selected
uv pip install -r build/requirements_build.txt
uv pip install -r app/requirements_app.txt
```

---

## Document Source Formats

| Extension | Parser | Notes |
|-----------|--------|-------|
| `.docx` | `python-docx` | Standard XML zip |
| `.pptx` | `python-pptx` | Standard XML zip |
| `.doc` | Word COM/pywin32 (Windows) or `antiword` (Linux) for OLE2; regex stripper for RTF | Detected by magic bytes |
| `.DOC` | Same as `.doc` | Uppercase variant |
| `.pub` | Quarantine | Microsoft Publisher — no free parser |

---

## Implementation Status

All 9 scripts implemented and tested:

### Build Helpers
- `build/format_detect.py` — magic-byte format detection (OLE2/RTF/OOXML)
- `build/normalize_scripture.py` — 66-book alias → canonical name mapping
- `build/parse_filename.py` — scripture-first / date-YYMMDD / date-MDDYY / numbered / plain
- `build/chunk_text.py` — sentence-aware sliding window chunker (protect/restore abbreviations)

### Build Pipeline
- `build/01_ingest_files.py` — 10-step quarantine pipeline; antiword for OLE2; 153/253 accepted
- `build/02_chunk_embed.py` — 7240 chunks; BGE-small-en-v1.5 embeddings; FAISS IndexFlatL2

### App
- `app/retriever.py` — FAISS dense + FTS5 sparse + RRF fusion hybrid retrieval
- `app/llm.py` — llama-cpp Phi-3.5-mini wrapper with pastoral system prompt
- `app/app.py` — Gradio 5 Blocks UI (graceful degradation if LLM missing)

### Notes
- `app/__init__.py` and `build/__init__.py` required (prevent `app/app.py` shadowing `app` namespace)
- `.doc` OLE2 parsed via `antiword -t`; RTF via regex stripper; `.docx` via python-docx; `.pptx` via python-pptx
- All parse errors caught as `ParseError` → `manual_review` quarantine bucket

## Running the Pipeline

```bash
# 1. Ingest (already done for SampleData/)
.venv/bin/python build/01_ingest_files.py --source SampleData/ --verbose

# 2. Chunk + embed (already done)
.venv/bin/python build/02_chunk_embed.py

# 3. Test retrieval
.venv/bin/python app/retriever.py --query "What did I preach about grace?"

# 4. Download LLM (optional, ~2.4 GB)
.venv/bin/python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(repo_id='bartowski/Phi-3.5-mini-instruct-GGUF',
                filename='Phi-3.5-mini-instruct-Q4_K_M.gguf',
                local_dir='models/')
"

# 5. Launch app
.venv/bin/python app/app.py --port 7860
```
