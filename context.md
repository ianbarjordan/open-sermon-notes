# sermon-notes-offline — Project Context

Fully offline RAG desktop application for a pastor to query 27+ years of sermon notes.
Runs on Windows (native). No cloud services. No internet required at runtime.

---

## Architecture Overview

```
<sermon library folder>/   (any path — set in UI, persisted to data/settings.json)
       │
       ▼
build/01_ingest_files.py   ← detect format, parse text, apply 10-step quarantine filter
       │  writes → data/documents/<doc_id>.json  +  sermons.db documents table
       ▼
build/02_chunk_embed.py    ← chunk → BGE-small embeddings → FAISS + FTS5
       │  writes → data/sermons.faiss   (IndexFlatL2, 384-dim)
       │           data/sermons.db      (SQLite FTS5 chunks + document metadata + full text)
       │           data/id_map.json     (FAISS int position → chunk_id string)
       ▼
app/app.py   ← Gradio UI: query → hybrid retrieval (FAISS+FTS5+RRF) → Phi-3.5-mini → answer
```

---

## Module Architecture

### Build helpers (`build/`)

| Module | Responsibility |
|--------|---------------|
| `format_detect.py` | Read magic bytes → `'ole2'`, `'rtf'`, `'ooxml'`, or `'unknown'` |
| `normalize_scripture.py` | Map any book alias to canonical name (e.g. `"1Cor"` → `"1 Corinthians"`) |
| `parse_filename.py` | Extract scripture ref / date / series number / title from filename stem |
| `chunk_text.py` | Sentence-aware sliding window chunker |

### Build pipeline (`build/`)

| Script | Responsibility |
|--------|---------------|
| `01_ingest_files.py` | Walk source dir; dispatch OLE2/RTF/DOCX/PPTX parsers; 10-step quarantine; write JSON + DB |
| `02_chunk_embed.py` | Load JSON docs (or DB fallback); chunk; embed; write FAISS + FTS5 + id_map |

### App (`app/`)

| Module | Responsibility |
|--------|---------------|
| `config.py` | All constants and paths — single source of truth |
| `logging_config.py` | Rotating file logger (5 MB × 3); `logs/app.log` |
| `retriever.py` | `load_retriever(sermon_root=)` factory; hybrid dense+sparse+RRF search |
| `llm.py` | `load_llm()` factory; `detect_n_gpu_layers()` auto-GPU; `LLM.generate()` |
| `handlers.py` | Minimal shared helpers — currently just `reload_retriever()`; absorbs more during Item 18 split |
| `app.py` | Gradio Blocks UI; 3 tabs: Search, Quarantine, Manage Archive |

---

## Data Flow

1. **Ingest** — `01_ingest_files.py` reads each source file, detects format, parses to plain text,
   runs 10-step quarantine checks, writes accepted files as JSON to `data/documents/` AND inserts
   into the `documents` table in `sermons.db` (sha256, relative source_file path, full text).
2. **Chunk + Embed** — `02_chunk_embed.py` loads from JSON (falls back to DB if JSON absent),
   splits text into ~150-word windows, encodes with BGE-small-en-v1.5 (384-dim),
   adds vectors to `IndexFlatL2`, inserts into SQLite FTS5, saves all artifacts.
   Incremental mode: compares sha256 against DB registry — only new/changed docs are embedded.
3. **Query** — `app.py` loads artifacts once at startup. On each query:
   - FAISS ANN search (with BGE query prefix)
   - FTS5 BM25 keyword search (sanitized OR tokens)
   - Reciprocal Rank Fusion (K=60) merges both lists
   - Always fetches MAX_TOP_K=50; shows min(slider, high-confidence) results
   - Top 4 chunks passed to Phi-3.5-mini; LLM cites title + scripture ref

---

## Quarantine Pipeline (10 steps in order)

| Step | Condition | Destination |
|------|-----------|-------------|
| 1 | `.Identifier`, `.csv`, `.md` | Silent skip |
| 2 | Extension `.pub` | `format_pub/` |
| 3 | Admin keyword in filename | `filename_flagged/` |
| 4 | Parse fails / Word-blocked | `manual_review/` |
| 5 | `word_count < MIN_CHUNK_WORDS` | `too_short/` |
| 6 | PPTX: >80% short-line-only slides | `worship_slides/` |
| 7 | PPTX: <3 text-bearing slides | `sparse_pptx/` |
| 8 | Faith keyword hits < 2 | `non_faith/` |
| 9 | SHA-256 already seen | `duplicates/` |
| 10 | — | **Accepted → write JSON + DB row** |

---

## Document Parsing by Format

| Extension | Format detection | Parser |
|-----------|-----------------|--------|
| `.docx` | `PK\x03\x04` magic (OOXML) | `python-docx` |
| `.pptx` | `PK\x03\x04` magic (OOXML) | `python-pptx` |
| `.doc` / `.DOC` | `\xd0\xcf\x11\xe0` (OLE2) | Word COM via `pywin32` (Windows) |
| `.doc` (some) | `{\` magic (RTF) | Regex stripper |
| `.pub` | OLE2 subtype | Quarantined — no free parser |

---

## Key Configuration (`app/config.py`)

| Constant | Value | Notes |
|----------|-------|-------|
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | 384-dim |
| `MODEL_PATH` | `models/Phi-3.5-mini-instruct-Q4_K_M.gguf` | ~2.4 GB |
| `CTX_WINDOW` | `4096` | Phi-3.5-mini context |
| `N_GPU_LAYERS` | `0` | Override; auto-detection via `detect_n_gpu_layers()` |
| `TOP_K` | `5` | Default slider value (minimum shown) |
| `MAX_TOP_K` | `50` | Internal retrieval pool (auto-expansion ranks across this many) |
| `MAX_VISIBLE_ROWS` | `20` | Hard cap on rows shown in the results table |
| `AUTO_EXPAND_THRESHOLD` | `0.023` | ≈70% of RRF max — auto-expands results beyond slider |
| `LOW_CONFIDENCE_THRESHOLD` | `0.018` | Below this, warn user |
| `RRF_K` | `60` | Reciprocal Rank Fusion constant |
| `SERMON_ROOT` | `""` | Resolved at runtime from `data/settings.json` |
| `QUARANTINE_ROOT` | `raw/quarantine` | 8 reason subdirs |
| `DB_PATH` | `data/sermons.db` | SQLite FTS5 + documents table |
| `FAISS_PATH` | `data/sermons.faiss` | IndexFlatL2 |
| `SETTINGS_PATH` | `data/settings.json` | Persisted UI settings |

---

## UI — Three Tabs

### 🔍 Search
- Full-width single-line query box; Enter or Search button submits
- Answer box with pastoral styling (warm left border accent)
- Matching Passages dataframe (capped at `MAX_VISIBLE_ROWS`=20 so it stays scannable)
- Min. results slider: sets floor; auto-expansion adds high-confidence results beyond it
  without re-searching (slider change re-slices cached pool via `expand_results()`)
- Row click or Row # + Open File button opens source file in native app
- `chunks_state` gr.State stores the full MAX_TOP_K pool fetched per query
- B-4 guard: if no sermon folder is configured, a setup-guidance message
  replaces results — the retriever is never invoked on an unconfigured library

### ⚠️ Quarantine
- Summary line with Refresh button
- One accordion per non-empty bucket, ordered by descending file count
- `manual_review` (Word-blocked .doc) opens by default; hint links to Unblock button
- Buckets >200 files capped at 200 with batch-unblock guidance
- Per-bucket batch buttons: **Delete All (N)** and **Force Ingest All (N)** route
  through a shared confirmation panel before any destructive action runs
- Per-file: Force Ingest (unblock + copy to library + re-ingest + reload retriever)
  or Ignore — **Ignore also routes through the confirmation panel** (B-6)

### 📁 Manage Archive
- Sermon library folder path + Browse button (Windows native tkinter picker)
- Folder path validation rejects quote characters `"` / `'` (B-7); changing
  the path shows a restart-required notice
- Process New Files (incremental) / Full Rebuild buttons
- **Full Rebuild routes through a confirmation panel** before running (S-8)
- All long-running buttons use generator wrappers that yield an immediate
  "Working..." state, then the final result — pastor sees the click register (S-1)
- Summary markdown + collapsed Technical log accordion
- Unblock Sermon Library (PowerShell Unblock-File, Windows only); failure
  messages are classified (Administrator-permission / folder-missing / generic)
  and give a concrete next step (S-9)
- Open Log Folder button

---

## Path Portability

`source_file` is stored **relative** to the sermon library root (e.g. `2019/Grace.docx`).
The retriever resolves it to absolute at query time: `Path(sermon_root) / relative_path`.
`sermon_root` is read from `data/settings.json` at startup — never hardcoded.

---

## DB Consolidation

`sermons.db` documents table schema:
```sql
CREATE TABLE documents (
    doc_id        TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    source_file   TEXT NOT NULL,   -- relative path
    title         TEXT,
    scripture_ref TEXT,
    date          TEXT,
    format        TEXT,
    word_count    INTEGER,
    text          TEXT,            -- full document text
    ingested_at   TEXT DEFAULT (datetime('now'))
);
```
`02_chunk_embed.py` falls back to this table if `data/documents/` JSON files are absent,
enabling a pre-built search bundle to ship without the intermediate JSON staging files.

---

## SHA-256 Stale Detection

During `--incremental`, `02_chunk_embed.py` queries `SELECT doc_id, sha256 FROM documents`,
compares against each doc's current hash:
- **New doc_id** → embed and insert
- **Same hash** → skip (no change)
- **Changed hash** → remove old SQLite chunks, re-embed, update hash; warn that a Full Rebuild
  is needed to purge orphaned FAISS vectors (IndexFlatL2 doesn't support deletion)

---

## Auto-GPU Detection (`app/llm.py`)

`detect_n_gpu_layers()` at LLM load time:
1. If `N_GPU_LAYERS != 0` in config → use that value (manual override)
2. `llama_cpp.llama_supports_gpu_offload()` → True means CUDA/Metal compiled wheel
3. `torch.cuda.is_available()` → fallback
4. Returns 0 (CPU) if no GPU confirmed

Default when GPU detected: 32 layers (all of Phi-3.5-mini).
Target deployment machine is CPU-only; ship standard CPU wheel.

---

## Logging

`app/logging_config.py`:
- `logs/app.log` — RotatingFileHandler, 5 MB × 3 files
- stderr — WARNING+ only
- "Open Log Folder" button in Manage Archive tab opens `logs/` in Explorer

---

## Dependencies

### Build (`build/requirements_build.txt`)
All versions pinned exactly (S-11).
- `sentence-transformers==3.4.1` — BGE-small embedding
- `faiss-cpu==1.13.2` — vector index
- `python-docx==1.2.0`, `python-pptx==0.6.23` — OOXML parsing
- `numpy==2.4.4`, `tqdm==4.67.3`, `huggingface_hub==0.36.2`
- `pywin32==311` *(Windows only)*

### App (`app/requirements_app.txt`)
All versions pinned exactly (S-11) — required for reproducible PyInstaller builds.
- `gradio==6.12.0` — Blocks web UI
- `llama-cpp-python==0.3.16` — CPU build for target machine
- `faiss-cpu==1.13.2`, `sentence-transformers==3.4.1`, `numpy==2.4.4`

### System
- Python 3.11
- SQLite 3.35+ with FTS5 (standard in Python 3.11)
- Microsoft Word (for `.doc` COM parsing on Windows)

---

## Environment Setup (Windows)

```bat
cd open-sermon-notes
uv venv .venv --python 3.11
.venv\Scripts\activate

pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -r build\requirements_build.txt
uv pip install -r app\requirements_app.txt

:: Verify pywin32 (run as Administrator)
python .venv\Lib\site-packages\pywin32_postinstall.py -install
```

---

## Running the Pipeline

```bat
:: 1. Ingest
python build\01_ingest_files.py --source "C:\Sermons" --verbose

:: 2. Embed
python build\02_chunk_embed.py

:: 3. Download model (one-time, ~2.4 GB)
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='bartowski/Phi-3.5-mini-instruct-GGUF', filename='Phi-3.5-mini-instruct-Q4_K_M.gguf', local_dir='models')"

:: 4. Launch
launch.bat
```

---

## Production Corpus (April 2026)

| Metric | Value |
|--------|-------|
| Source files processed | 14,110 |
| Accepted | 10,192 |
| FAISS vectors | ~585,000 |
| manual_review (Word-blocked) | 4,733 |
| duplicates | 11,063 |
| non_faith | 1,061 |
| too_short | 531 |

---

## Test Suite

213 tests across 7 test files. Run with:
```bat
.venv\Scripts\python.exe -m pytest tests\ -v
```

| File | Coverage |
|------|---------|
| `test_app_handlers.py` | handle_query, expand_results, open_file, on_row_select, library-configured guard, quarantine handlers (incl. per-file ignore confirm), settings, archive handlers, generator progress wrappers, Full Rebuild confirm flow, quote-path validation, unblock failure classifier |
| `test_handlers.py` | reload_retriever success/failure paths |
| `test_config.py` | config constants, thresholds |
| `test_incremental_embed.py` | init_db, build_index_incremental, load_documents_from_db, sha256 stale detection |
| `test_ingest_registry.py` | hash registry load/save |
| `test_parse_filename.py` | filename parser |
| `test_retriever_utils.py` | FTS5 sanitize, RRF fusion |
| `test_llm.py` | detect_n_gpu_layers, _format_chunk, _build_user_message, stop-tokens regression (B-3) |
