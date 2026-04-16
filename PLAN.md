# Delivery Plan: open-sermon-notes

Pre-packaging refinement tasks, ordered by priority.
Last updated: 2026-04-15

---

## Tier 1 — Must ship  ✅ COMPLETE

### 1. Reinforce canonical library folder in UI  ✅
### 2. Fix startup race condition  ✅
### 3. Security guardrails  ✅
### 4. Input path validation before subprocess  ✅
### 5. File logging + "Open Log Folder" button  ✅
### 6. Friendly error messages in Manage Archive  ✅

---

## Tier 2 — Quality-of-life improvements  ✅ COMPLETE

### 7. Quarantine summary after ingest runs  ✅
### 8. Auto-heal "Unblock Sermon Library" button  ✅
### 9. Native Windows folder picker  ✅

---

## Tier 3 — Search UX + GUI polish

### 10. Dynamic result count + raised ceiling  (`app/config.py`, `app/app.py`)
- Raise `MAX_TOP_K` from 15 → **50**
- Default `TOP_K` stays 5
- **Dynamic auto-expansion:** retriever always fetches `MAX_TOP_K` candidates; `handle_query`
  returns at least `top_k` results, *plus* any additional results scoring ≥ 70% of the
  theoretical RRF max — up to `MAX_TOP_K`. This way a high-confidence query naturally
  surfaces all strong matches even if the user left the slider at 5.
  - Add `AUTO_EXPAND_THRESHOLD = 0.023` to `app/config.py`
    (= 70% × 2/61 ≈ 0.033; requires presence near the top of *both* dense and sparse lists)
  - Rename slider label from "Results" → "Min. results" so the behaviour is self-describing
- Update `row_count` on the results dataframe to `(MAX_TOP_K, "fixed")` so it tracks the
  ceiling automatically
- LLM context budget is unaffected — `_LLM_MAX_CHUNKS = 4` already caps what the model
  reads regardless of how many rows are shown in the table
- Rationale for 50: RRF scores drop steeply past ~25, so results beyond that are
  low-confidence browsing territory — exactly what a pastor scanning for a half-remembered
  sermon wants. 50 gives a practical ceiling without inviting LLM abuse.

### 11. GUI analysis and redesign  (`app/app.py`)
- Comprehensive review of the current Gradio UI against best practices and the use case:
  - Layout, visual hierarchy, and whitespace
  - Colour palette and typography — should feel calm, serious, and purposeful (pastoral,
    not corporate SaaS)
  - Component choices — are there better Gradio components for any current widgets?
  - Accessibility — contrast, label clarity, keyboard navigation
  - First-run experience — is the Search tab immediately usable, or does it need
    orientation text?
  - Manage Archive tab — does the new layout (summary + accordion + buttons) flow well?
- Produce a revised UI with concrete improvements, not just cosmetic tweaks

---

## Tier 4 — Portability foundations (required before packaging)

### 12. Relative path storage + SERMON_ROOT  (`app/config.py`, `app/retriever.py`, `build/01_ingest_files.py`)
- Add `SERMON_ROOT` to `app/config.py` (default: `""`, overridable via env var
  `SERMON_NOTES_ROOT` or the persistent `data/settings.json`)
- In `01_ingest_files.py`, store `source_file` as a path **relative to `--source`** root
  (not absolute). Example: `2019/Grace.docx` instead of `C:\Sermons\2019\Grace.docx`
- In `retriever.py`, resolve back to absolute at query time:
  `Path(SERMON_ROOT) / relative_source_file`
- Update `on_row_select()` and `open_file()` in `app/app.py` to use the resolved path
- Required for the shipping bundle to work on a machine other than the developer's

### 13. DB consolidation — store full text in SQLite  (`build/01_ingest_files.py`, `build/02_chunk_embed.py`)
- Add a `documents` table to `sermons.db`:
  `(doc_id TEXT PRIMARY KEY, source_file TEXT, title TEXT, scripture_ref TEXT, date TEXT,
   format TEXT, word_count INT, content_hash TEXT, full_text TEXT)`
- In `01_ingest_files.py`, write accepted documents to this table *in addition to* (or
  instead of) `data/documents/*.json`
- In `02_chunk_embed.py`, read from the `documents` table when JSON files are absent
- Allows shipping a "Search Bundle" (FAISS + DB) without 14k individual JSON files

### 14. SHA-256 stale-content detection  (`build/02_chunk_embed.py`)
- During `--incremental`, compare current file `content_hash` (from `documents` table)
  against the stored hash
- If hash differs: delete old chunks for that `doc_id`, re-embed, update the hash
- If hash matches: skip (no change)
- Requires item 13 (hash stored in `documents` table)

---

## Tier 5 — Pre-packaging UX completeness

### 15. Quarantine management UI  (`app/app.py`)
- Full sub-tab listing files in `raw/quarantine/` grouped by reason
- Per-file "Ignore" (mark permanently skipped) and "Force Ingest" (bypass quarantine)
- Reduces friction for users with Word-blocked files: instead of hunting in Explorer,
  they can see and act on every blocked file from within the app
- Effort: 3–4 hours

### 16. Auto-GPU detection  (`app/config.py`, `app/llm.py`)
- Detect at startup: if `torch.cuda.is_available()` and a CUDA-capable llama-cpp build
  is present, set `N_GPU_LAYERS = 32` (safe default for Phi-3.5-mini on most GPUs)
- Log the decision at startup so the user can see whether GPU is active
- Effort: ~1 hour; meaningful speedup only for users with NVIDIA GPUs

---

## Tier 6 — Packaging & distribution

### 17. PyInstaller / portable launcher
- Only feasible after Tier 4 is complete (absolute paths break frozen builds)
- Use `--onedir` mode (not `--onefile` — llama-cpp native libs won't bundle cleanly)
- Update `_PROJECT_ROOT` detection to handle `sys.frozen` (PyInstaller) vs source mode:
  ```python
  if getattr(sys, 'frozen', False):
      _PROJECT_ROOT = Path(sys.executable).parent
  else:
      _PROJECT_ROOT = Path(__file__).resolve().parent.parent
  ```
- Bundle the Gradio static assets (they're in the venv, not auto-detected)
- `setup.bat` remains for fresh-install (Python + deps); PyInstaller build produces a
  separate launcher that doesn't require Python to be installed

---

## Execution order

```
Now    →  Tier 3 (items 10–11)   quick wins: max results + GUI polish
Next   →  Tier 4 (items 12–14)   portability refactor, prep for packaging
Then   →  Tier 5 (items 15–16)   quarantine UI + auto-GPU (pre-packaging UX)
Final  →  Tier 6 (item 17)       packaging, test on clean machine
```
