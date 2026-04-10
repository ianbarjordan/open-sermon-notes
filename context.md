# sermon-notes-offline — Project Context

Fully offline RAG desktop application for a pastor to query 27+ years of sermon notes.
Runs on Windows (native) and Linux/WSL. No cloud services required.

---

## Architecture Overview

```
SampleData/  (or any source dir)
       │
       ▼
build/01_ingest_files.py   ← detect format, parse text, apply 10-step quarantine filter
       │  writes → data/documents/<doc_id>.json   (one per accepted file)
       ▼
build/02_chunk_embed.py    ← sentence-aware chunking → BGE-small embeddings → FAISS + FTS5
       │  writes → data/sermons.faiss   (IndexFlatL2, 384-dim)
       │           data/sermons.db      (SQLite FTS5 chunks + document metadata)
       │           data/id_map.json     (FAISS int position → chunk_id string)
       ▼
app/app.py   ← Gradio UI: query → hybrid retrieval (FAISS + FTS5 + RRF) → Phi-3.5-mini → answer
```

---

## Module Architecture

### Build helpers (`build/`)

| Module | Responsibility |
|--------|---------------|
| `format_detect.py` | Read magic bytes → `'ole2'`, `'rtf'`, `'ooxml'`, or `'unknown'` |
| `normalize_scripture.py` | Map any book alias to canonical name (e.g. `"1Cor"` → `"1 Corinthians"`) |
| `parse_filename.py` | Extract scripture ref / date / series number / title from filename stem |
| `chunk_text.py` | Sentence-aware sliding window chunker; protect/restore abbreviations for regex compat |

### Build pipeline (`build/`)

| Script | Responsibility |
|--------|---------------|
| `01_ingest_files.py` | Walk source dir; dispatch OLE2/RTF/DOCX/PPTX parsers; 10-step quarantine; write JSON |
| `02_chunk_embed.py` | Load JSON docs; chunk; embed with BGE-small-en-v1.5; write FAISS + FTS5 + id_map |

### App (`app/`)

| Module | Responsibility |
|--------|---------------|
| `config.py` | All constants and paths — single source of truth |
| `retriever.py` | `load_retriever()` factory; `Retriever.search()` hybrid dense+sparse+RRF |
| `llm.py` | `load_llm()` factory; `LLM.generate()` wraps llama-cpp Phi-3.5-mini-instruct |
| `app.py` | Gradio Blocks UI; loads retriever + LLM once at startup; graceful LLM degradation |

---

## Data Flow

1. **Ingest** — `01_ingest_files.py` reads each source file, detects format via magic bytes,
   parses to plain text, runs 10-step quarantine checks, writes accepted files as JSON to
   `data/documents/`.
2. **Chunk + Embed** — `02_chunk_embed.py` loads the JSONs, splits text into overlapping
   ~150-word windows, encodes each chunk with BGE-small-en-v1.5 (384-dim, normalized),
   adds vectors to a `faiss.IndexFlatL2`, inserts chunk text into SQLite FTS5, saves all
   three artifacts.
3. **Query** — `app.py` loads the three artifacts once at startup. On each query:
   - FAISS ANN search with `EMBED_QUERY_PREFIX` prepended to the query
   - FTS5 BM25 keyword search with sanitized token OR expression
   - Reciprocal Rank Fusion (RRF, K=60) merges both ranked lists
   - Top-5 chunks above `CONFIDENCE_THRESHOLD` passed to Phi-3.5-mini
   - LLM answers strictly from provided excerpts; cites title + scripture ref

---

## Quarantine Pipeline (10 steps in order)

| Step | Condition | Destination |
|------|-----------|-------------|
| 1 | `.Identifier`, `.csv`, `.md` | Silent skip |
| 2 | Extension `.pub` | `format_pub/` |
| 3 | Admin keyword in filename | `filename_flagged/` |
| 4 | Parse fails | `manual_review/` |
| 5 | `word_count < MIN_CHUNK_WORDS` | `too_short/` |
| 6 | PPTX: >80% short-line-only slides | `worship_slides/` |
| 7 | PPTX: <3 text-bearing slides | `sparse_pptx/` |
| 8 | Faith keyword hits < 2 | `non_faith/` |
| 9 | SHA-256 already seen | `duplicates/` |
| 10 | — | **Accepted → write JSON** |

---

## Document Parsing by Format

| Extension | Format detection | Parser |
|-----------|-----------------|--------|
| `.docx` | `PK\x03\x04` magic (OOXML) | `python-docx` |
| `.pptx` | `PK\x03\x04` magic (OOXML) | `python-pptx` |
| `.doc` / `.DOC` | `\xd0\xcf\x11\xe0` (OLE2) | **Windows:** Word COM via `pywin32`; **Linux:** `antiword -t` |
| `.doc` (some) | `{\` magic (RTF) | Regex stripper — strips control words, decodes `\'XX` cp1252 escapes |
| `.pub` | OLE2 subtype | Quarantined — no free parser |

A single Word COM instance is opened once per ingest run on Windows (not per file) for performance.

---

## Key Configuration (`app/config.py`)

| Constant | Value | Notes |
|----------|-------|-------|
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | 384-dim, ~33 MB download |
| `EMBED_QUERY_PREFIX` | `"Represent this sentence..."` | Required for BGE asymmetric retrieval |
| `EMBEDDING_DIM` | `384` | Must match FAISS index dim |
| `MODEL_PATH` | `models/Phi-3.5-mini-instruct-Q4_K_M.gguf` | ~2.4 GB, download separately |
| `CTX_WINDOW` | `4096` | Phi-3.5-mini context length |
| `N_GPU_LAYERS` | `0` | Set >0 to offload layers to GPU |
| `N_THREADS` | `max(1, cpu_count//2)` | Guards against `None` on some VMs |
| `TOP_K` | `5` | Chunks returned to LLM |
| `RRF_K` | `60` | Reciprocal Rank Fusion constant |
| `CONFIDENCE_THRESHOLD` | `0.005` | Min RRF score (max ~0.033 with K=60) |
| `MIN_CHUNK_WORDS` | `50` | Discard chunks shorter than this |
| `COMMENTARY_CHUNK_WORDS` | `150` | Target chunk size |
| `DB_PATH` | `data/sermons.db` | SQLite FTS5 |
| `FAISS_PATH` | `data/sermons.faiss` | FAISS IndexFlatL2 |
| `ID_MAP_PATH` | `data/id_map.json` | `{int_pos: chunk_id}` |
| `DOCUMENTS_DIR` | `data/documents` | Intermediate JSON store |

---

## Dependencies

### Build phase (`build/requirements_build.txt`)
- `sentence-transformers>=3.0` — BGE-small embedding
- `faiss-cpu>=1.8` — vector index
- `python-docx>=1.1` — `.docx` parsing
- `python-pptx>=0.6` — `.pptx` parsing
- `numpy>=1.26`
- `tqdm>=4.66`
- `pywin32>=306` *(Windows only, auto-selected via `sys_platform` marker)*

### App phase (`app/requirements_app.txt`)
- `gradio>=5.0` — Blocks web UI (tested with 6.11)
- `llama-cpp-python==0.3.16` — Phi-3.5-mini inference
- `faiss-cpu>=1.8`
- `sentence-transformers>=3.0`
- `numpy>=1.26`

### System
- Python 3.11
- SQLite 3.35+ with FTS5 (standard in Python 3.11)
- **Windows:** Microsoft Word (for `.doc` COM parsing)
- **Linux/WSL:** `antiword` (`sudo apt-get install antiword`)

---

## Package / Import Notes

- `app/__init__.py` and `build/__init__.py` are required empty files. Without them,
  Python treats `app/` as a namespace package and `app/app.py` shadows the `app` package
  name on the `sys.path`, causing `ModuleNotFoundError: 'app' is not a package`.
- All scripts add the project root to `sys.path` via
  `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`.

---

## Environment Setup

### Windows (native)

```powershell
# Prerequisites:
#   Python 3.11   https://python.org/downloads
#   uv            https://docs.astral.sh/uv/getting-started/installation/
#   Microsoft Word (for .doc parsing)

cd open-sermon-notes

uv venv .venv --python 3.11
.venv\Scripts\activate

# Torch CPU build (sufficient for embeddings + inference)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# All other dependencies (pywin32 installed automatically on Windows)
pip install -r build/requirements_build.txt
pip install -r app/requirements_app.txt

# Register pywin32 COM components (required once after install)
python .venv\Scripts\pywin32_postinstall.py -install
```

### Linux / WSL

```bash
cd sermon-notes-offline
sudo apt-get install -y antiword

uv venv .venv --python 3.11
uv pip install torch                           # CUDA wheel auto-selected
uv pip install -r build/requirements_build.txt
uv pip install -r app/requirements_app.txt
```

---

## Running the Pipeline

### Windows
```powershell
# 1. Ingest source files
python build\01_ingest_files.py --source SampleData --verbose

# 2. Chunk + embed
python build\02_chunk_embed.py

# 3. Download LLM model (~2.4 GB, one-time)
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='bartowski/Phi-3.5-mini-instruct-GGUF', filename='Phi-3.5-mini-instruct-Q4_K_M.gguf', local_dir='models')"

# 4. Launch app
python app\app.py --port 7860
```

### Linux / WSL
```bash
.venv/bin/python build/01_ingest_files.py --source SampleData/ --verbose
.venv/bin/python build/02_chunk_embed.py
.venv/bin/python app/app.py --port 7860
```

Open `http://127.0.0.1:7860` in your browser.

---

## Verified Results (SampleData, 253 files)

| Outcome | Count |
|---------|-------|
| accepted | 153 |
| skipped (.Identifier / .csv / .md) | 21 |
| too_short | 19 |
| non_faith | 18 |
| filename_flagged | 15 |
| format_pub | 13 |
| manual_review | 10 |
| worship_slides | 3 |
| duplicates | 1 |
| **FAISS vectors** | **7,240** |
| **FTS5 chunks** | **7,240** |
