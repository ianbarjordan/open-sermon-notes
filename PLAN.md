# Delivery Plan: open-sermon-notes

Pre-packaging refinement tasks, ordered by priority.
Last updated: 2026-04-16
Next session: start with item 17 (PyInstaller packaging)

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

## Tier 3 — Search UX + GUI polish  (partially complete)

### 10. Dynamic result count + raised ceiling  ✅  (`app/config.py`, `app/app.py`)
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

### 12. Relative path storage + SERMON_ROOT  ✅
- Add `SERMON_ROOT` to `app/config.py` (default: `""`, overridable via env var
  `SERMON_NOTES_ROOT` or the persistent `data/settings.json`)
- In `01_ingest_files.py`, store `source_file` as a path **relative to `--source`** root
  (not absolute). Example: `2019/Grace.docx` instead of `C:\Sermons\2019\Grace.docx`
- In `retriever.py`, resolve back to absolute at query time:
  `Path(SERMON_ROOT) / relative_source_file`
- Update `on_row_select()` and `open_file()` in `app/app.py` to use the resolved path
- Required for the shipping bundle to work on a machine other than the developer's

### 13. DB consolidation — store full text in SQLite  ✅
- Add a `documents` table to `sermons.db`:
  `(doc_id TEXT PRIMARY KEY, source_file TEXT, title TEXT, scripture_ref TEXT, date TEXT,
   format TEXT, word_count INT, content_hash TEXT, full_text TEXT)`
- In `01_ingest_files.py`, write accepted documents to this table *in addition to* (or
  instead of) `data/documents/*.json`
- In `02_chunk_embed.py`, read from the `documents` table when JSON files are absent
- Allows shipping a "Search Bundle" (FAISS + DB) without 14k individual JSON files

### 14. SHA-256 stale-content detection  ✅
- During `--incremental`, compare current file `content_hash` (from `documents` table)
  against the stored hash
- If hash differs: delete old chunks for that `doc_id`, re-embed, update the hash
- If hash matches: skip (no change)
- Requires item 13 (hash stored in `documents` table)

---

## Tier 5 — Pre-packaging UX completeness

### 15. Quarantine management UI  ✅  (`app/app.py`)
- Full sub-tab listing files in `raw/quarantine/` grouped by reason
- Per-file "Ignore" (mark permanently skipped) and "Force Ingest" (bypass quarantine)
- Reduces friction for users with Word-blocked files: instead of hunting in Explorer,
  they can see and act on every blocked file from within the app
- Effort: 3–4 hours

### 16. Auto-GPU detection  ✅  (`app/llm.py`)
- Detect at startup: if `torch.cuda.is_available()` and a CUDA-capable llama-cpp build
  is present, set `N_GPU_LAYERS = 32` (safe default for Phi-3.5-mini on most GPUs)
- Log the decision at startup so the user can see whether GPU is active
- Effort: ~1 hour; meaningful speedup only for users with NVIDIA GPUs

---

## Pre-delivery Code Review  ✅ COMPLETE (2026-05-13)

16-commit pass landed before Item 17. Findings + plan archived at
`C:\Users\Ian\.claude\plans\graceful-tickling-gray*.md`.

Commits in order:
- S-4 silent-except logging · S-3 print→logging · B-3 LLM stop tokens
- B-4 library-configured guard · B-6 per-file Ignore confirm · B-7 quote-path reject
- S-1 working-state generators · S-2 sanitized errors · S-5 missing-model copy
- S-6/S-7 launch.bat hardening · S-8 Full Rebuild confirm · S-9 unblock classifier
- S-10 MAX_VISIBLE_ROWS=20 cap · S-11 pinned requirements
- D-1 (minimal) `app/handlers.py` w/ `reload_retriever()`
- Docs sweep (this commit)

213 tests passing at the end of the review.

---

## Tier 6 — Packaging & distribution  ✅ COMPLETE (2026-05-16)

### 17. PyInstaller / portable launcher  ✅

9-commit pass: 17a renamed build scripts (drop numeric prefix) → 17b/17c
extracted `build_parser`/`run(args)`/`main(argv)` from each → 17d added
`handlers.run_ingest` / `run_embed` with stdout+stderr+logging capture →
17e replaced six `sys.executable` subprocess sites with in-process calls
(B-1 resolved) → 17f added `app/paths.py` with `is_frozen`/`project_root`/
`data_root`/`resolve_writable`, wired through app + logging + handlers
(B-2 resolved) → 17g landed `sermon_notes.spec`, `pyi_rth_libs.py`
runtime hook, `build/requirements_packaging.txt`, `build/make_release.bat`
→ 17h iterated on the spec (CUDA strip, safehttpx/groovy, backports) and
created `build/setup_release_venv.bat` for a CPU-torch-only release venv
→ 17i auto-detects torch flavor in the spec and switched
`setup_release_venv.bat` to direct `python.exe -m pip`.

Shipping artifacts (verified end-to-end on the dev machine):
- `dist/SermonNotes/SermonNotes.exe` ≈ 886 MB; boots, loads Gradio,
  serves HTTP 200 on 127.0.0.1
- `build/setup_release_venv.bat` — one-time CPU-torch release venv setup
- `build/make_release.bat` — repeatable release builder; refuses to ship
  if the test suite is red or the build venv has CUDA torch
- `sermon_notes.spec` — auto-detects CPU vs CUDA torch and applies the
  strip only when needed; pefile-verified DLL patterns
- `pyi_rth_libs.py` — runtime hook fixing numpy 2.x DLL search path

230 tests passing at completion.

---

### 17 — Historical scope notes (preserved for reference)

**Three architectural changes absorbed from the pre-delivery review (B-1, B-2)
that are scope-of-Item-17 — they cannot be patched, they are the packaging work.**

#### B-1 · In-process build pipeline (single largest piece of Item 17)
The four archive/quarantine handlers currently spawn `sys.executable
build/NN_script.py` to run the build scripts. Under a frozen PyInstaller
bundle `sys.executable` is the launcher `.exe` — there is no python
interpreter to hand a script to. Every Process New Files / Full Rebuild /
Force Ingest call will fail at runtime once packaged.

Refactor `build/01_ingest_files.py` and `build/02_chunk_embed.py` to
expose `main()` as importable callables. `handlers.py` imports them and
runs in-process, routing their stdout/stderr through the root logger so
the technical-log accordion still gets the same output.

Drop every `sys.executable` subprocess spawn (6 sites in app.py).

#### B-2 · `sys.frozen` path resolution
```python
if getattr(sys, 'frozen', False):
    _PROJECT_ROOT = Path(sys.executable).parent
else:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
```
Same fix in `app/logging_config.py`. **Writable paths** (data/, logs/,
raw/quarantine/) move to `%LOCALAPPDATA%/SermonNotes/` so they persist
across runs and don't collide with read-only `_MEIPASS`. **Bundled
assets** (default settings template, etc.) stay under `_MEIPASS`.

#### Packaging mechanics
- `--onedir` mode (not `--onefile` — llama-cpp native libs don't bundle cleanly)
- Hidden imports to enumerate: `faiss`, `llama_cpp`, `sentence_transformers.*`,
  `gradio.*`, `huggingface_hub`, `pywin32`
- Bundle the Gradio static assets (they're in the venv, not auto-detected)
- `setup.bat` remains for fresh-install (Python + deps); the PyInstaller
  build produces a separate launcher that doesn't require Python to be
  installed
- First-run migration: copy any pre-existing `data/`, `logs/`, `raw/` from
  the install dir into `%LOCALAPPDATA%/SermonNotes/`
- Standard build: `build/make_release.bat` — runs PyInstaller, smoke test,
  zips `dist/`
- Smoke test corpus includes one accented-filename sermon (D-2 from review)

**Target machine: CPU-only (integrated graphics, no dedicated GPU)**
- Ship the standard CPU llama-cpp-python wheel — no CUDA dependencies to bundle
- `detect_n_gpu_layers()` returns 0 and the app runs on CPU

---

## Tier 7 — Post-packaging polish

### 18. Deep GUI analysis and redesign (round 2) + structural split

**Task 1 — Full UI-block split** (deferred from pre-delivery review D-1)

Split `app/app.py` (currently ~1500 lines after the review changes) into:
- `app/app.py` — main(), CLI, build_ui() composition, _load_components,
  settings persistence
- `app/ui_search.py` — search tab block builder
- `app/ui_quarantine.py` — quarantine tab block builder
- `app/ui_archive.py` — manage-archive tab block builder
- `app/handlers.py` (already exists) — absorbs `_run_subprocess`,
  `_validate_and_persist_folder`, `_build_run_summary` and friends

After Item 17's B-1 in-process refactor, handlers are pure Python instead
of subprocess orchestrators, which makes this split much cleaner.

**Task 2 — Real-world UX pass**
- Information hierarchy: does the pastor know exactly what to do on first launch?
- Quarantine tab: is the per-file list usable with 4,700+ entries, or does it
  need grouping, filtering, or pagination?
- Typography, spacing, colour refinement — push beyond Gradio defaults toward a
  genuinely bespoke pastoral aesthetic
- Accessibility: contrast ratios, keyboard navigation, label clarity
- Feedback from the end user after first real-world use should drive this pass

**Task 3 — Deferred backlog from the pre-delivery review**
- D-2 Non-ASCII filename round-trip empirical test
- D-3 Long-path (>260) support — currently documented as a soft limit
- D-4 Empty-state messaging on Search tab (`row_count=(0, "dynamic")`)
- D-5 IndexIDMap migration for proper FAISS deletion (orphan vectors)
- D-6 Sentence-aware truncation of long chunks in LLM context
- D-7 Deep typography/accessibility polish
- D-8 (None — was an unrelated nit, resolved in the docs sweep)

Effort: 1–2 days depending on user feedback scope.
Prerequisite: Item 17 shipped and pastor has used the packaged build.

---

## Execution order

```
Done   →  Tiers 1–5 (items 1–16)  ✅ complete
Next   →  Tier 6 (item 17)         PyInstaller packaging, test on clean machine
Final  →  Tier 7 (item 18)         GUI polish round 2, driven by real-world use
```

### Notes on future acceleration (post-delivery, not in scope)
- **Vulkan backend** (Intel/AMD integrated GPU): modest 1.5–2× LLM speedup without
  CUDA complexity; requires Vulkan-compiled llama-cpp-python wheel — worth exploring
  for a future version once the target machine spec is confirmed
- **NPU support** (Intel NPU / Qualcomm QNN): requires explicit backend compilation;
  not broadly available via standard pip wheels yet — monitor llama.cpp releases
