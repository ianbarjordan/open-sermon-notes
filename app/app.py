"""
app.py — Gradio UI for AI-Powered Sermon Note Search.

Usage:
    python app/app.py --port 7860
    python app/app.py --host 127.0.0.1 --port 7861
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import (  # noqa: E402
    AUTO_EXPAND_THRESHOLD,
    DB_PATH,
    FAISS_PATH,
    ID_MAP_PATH,
    LOW_CONFIDENCE_THRESHOLD,
    MAX_TOP_K,
    MODEL_PATH,
    QUARANTINE_LABELS,
    QUARANTINE_ROOT,
    SETTINGS_PATH,
    TOP_K,
)
from app.logging_config import get_logger, log_dir, setup_logging  # noqa: E402

# ---------------------------------------------------------------------------
# Global retriever + LLM (loaded once at startup)
# ---------------------------------------------------------------------------
_retriever = None
_llm = None

# Project root (parent of app/)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


# ---------------------------------------------------------------------------
# Persistent settings (data/settings.json)
# ---------------------------------------------------------------------------

def _settings_path() -> Path:
    return Path(_PROJECT_ROOT) / SETTINGS_PATH


def load_settings() -> dict:
    p = _settings_path()
    if p.exists():
        try:
            with open(p, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def save_settings(settings: dict) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(settings, fh, indent=2)
    except Exception:
        pass


def _load_components(
    db: str,
    faiss: str,
    idmap: str,
    model: str,
) -> tuple[str, str]:
    """Load retriever and LLM; return (retriever_status, llm_status)."""
    global _retriever, _llm
    _log = get_logger(__name__)

    ret_status = "Retriever: not loaded"
    llm_status = "LLM: not loaded"

    try:
        from app.retriever import load_retriever
        _settings = load_settings()
        _sermon_root = _settings.get('sermon_library_folder', '')
        _retriever = load_retriever(db_path=db, faiss_path=faiss, idmap_path=idmap,
                                    sermon_root=_sermon_root)
        ret_status = "Retriever: loaded"
    except Exception as e:
        ret_status = f"Retriever ERROR: {e}"
        _log.error("Retriever failed to load", exc_info=True)

    try:
        from app.llm import load_llm
        _llm = load_llm(model_path=model)
        llm_status = "LLM: loaded"
    except FileNotFoundError as e:
        llm_status = f"LLM: model not found — {e}"
        _log.warning("LLM model file not found: %s", e)
    except Exception as e:
        llm_status = f"LLM ERROR: {e}"
        _log.error("LLM failed to load", exc_info=True)

    return ret_status, llm_status


# ---------------------------------------------------------------------------
# Query handler
# ---------------------------------------------------------------------------

def _build_result_rows(chunks: list) -> list:
    """Convert a list of chunk dicts into Gradio dataframe rows."""
    RRF_MAX = 2.0 / 61.0
    rows = []
    for i, c in enumerate(chunks):
        snippet = (c.get('text') or '')[:120] + '...'
        match_pct = f"{min(c.get('score', 0) / RRF_MAX * 100, 100):.0f}%"
        source_path = c.get('source_file') or ''
        source_display = Path(source_path).name if source_path else ''
        rows.append([
            i + 1,
            c.get('title') or '',
            c.get('scripture_ref') or '',
            c.get('date') or '',
            snippet,
            match_pct,
            source_display,
        ])
    return rows


def _slice_chunks(all_chunks: list, top_k: int) -> tuple[list, str]:
    """Apply the min-results floor + auto-expansion logic to an already-fetched list.

    Returns (visible_chunks, status_text).
    chunks_state always holds the full MAX_TOP_K pool; this function decides what to
    *show* based on the current slider value.
    """
    min_results = int(top_k)
    base = all_chunks[:min_results]
    expanded = [
        c for c in all_chunks[min_results:]
        if c.get('score', 0) >= AUTO_EXPAND_THRESHOLD
    ]
    visible = base + expanded

    if not visible:
        return [], ""

    max_score = max(c.get('score', 0) for c in visible)
    if max_score < LOW_CONFIDENCE_THRESHOLD:
        status = (
            f"⚠️ Low confidence ({max_score:.3f}) — "
            "this topic may not be in your archive. "
            "Results shown are the closest matches available."
        )
    elif len(visible) > min_results and expanded:
        status = (
            f"{len(visible)} result(s) — {len(expanded)} additional high-confidence "
            f"match(es) included automatically"
        )
    else:
        status = f"{len(visible)} result(s) returned"

    return visible, status


def handle_query(query: str, top_k: int = TOP_K):
    """Search handler — returns (answer, dataframe_rows, status, chunks_state).

    chunks_state stores the FULL MAX_TOP_K pool so the slider can re-slice it
    without re-running a search.
    """
    empty = ("Please enter a question.", [], "No query.", [])

    if not query or not query.strip():
        return empty

    if _retriever is None:
        return ("Retriever is not available. Check startup logs.", [], "Error: retriever not loaded", [])

    try:
        # Always fetch the full MAX_TOP_K pool so auto-expansion has candidates to draw from
        all_chunks = _retriever.search(query, top_k=MAX_TOP_K)
    except Exception as e:
        return (f"Retrieval error: {e}", [], f"Error: {e}", [])

    if not all_chunks:
        return ("No relevant sermons found for this query.", [], "0 results", [])

    visible, status = _slice_chunks(all_chunks, top_k)

    # Build answer via LLM (or fallback if LLM not loaded)
    if _llm is not None:
        try:
            answer = _llm.generate(query, visible)
        except Exception as e:
            answer = f"(LLM error: {e})\n\nTop result: {visible[0].get('text', '')[:300]}"
    else:
        top = visible[0]
        answer = (
            f"**Note:** LLM not loaded — showing top match only.\n\n"
            f"**{top.get('title', '(untitled)')}** "
            f"({top.get('scripture_ref', '')})\n\n"
            f"{top.get('text', '')[:500]}..."
        )

    # Store the FULL pool in state — slider can expand without re-searching
    return answer, _build_result_rows(visible), status, all_chunks


def expand_results(top_k: int, chunks_state: list):
    """Re-slice the cached result pool when the slider moves — no new search needed.

    Returns (dataframe_rows, status_text).
    """
    if not chunks_state:
        return [], ""
    visible, status = _slice_chunks(chunks_state, top_k)
    return _build_result_rows(visible), status


# ---------------------------------------------------------------------------
# Row-click file open handler
# ---------------------------------------------------------------------------

def _extract_row_index(evt) -> int | None:
    """Extract the clicked row index from whatever Gradio passes to a select handler.

    Gradio 5.x passes SelectData (has .index as a non-callable attribute).
    Older builds may pass a plain (row, col) tuple of ints.
    Plain Python lists also have an .index *method* (callable) — guard against that.
    If neither is detected, returns None.
    """
    # SelectData: evt.index is a property/attribute (not callable), value is [row, col] or int
    if hasattr(evt, 'index') and not callable(evt.index):
        idx = evt.index
        if isinstance(idx, (list, tuple)):
            return int(idx[0])
        return int(idx)
    # Plain (row, col) tuple — both elements must be numbers
    if isinstance(evt, (list, tuple)) and evt and isinstance(evt[0], (int, float)):
        return int(evt[0])
    return None


def on_row_select(evt, chunks_state: list) -> str:
    """Fires when any cell in results_df is clicked. Opens source file for that row."""
    if evt is None:
        return ""
    row_index = _extract_row_index(evt)
    if row_index is None:
        return "Row click unavailable in this Gradio build — use the Result # field below."
    if not chunks_state or row_index >= len(chunks_state):
        return "No result selected."
    source = chunks_state[row_index].get('source_file', '')
    if not source:
        return "Source file path not available."
    path = Path(source).resolve()
    if not path.exists():
        return f"File not found: {path}"
    try:
        if sys.platform == 'win32':
            os.startfile(str(path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(path)], check=True)
        else:
            subprocess.run(['xdg-open', str(path)], check=True)
        return f"Opened: {path.name}"
    except Exception as e:
        return f"Could not open file: {e}"


# ---------------------------------------------------------------------------
# Number-input file open (reliable fallback for all Gradio versions)
# ---------------------------------------------------------------------------

def open_file(result_num: int, chunks_state: list) -> str:
    """Open the Nth result file. Used by the Result # + Open File button."""
    if not chunks_state:
        return "No search results. Run a search first."
    idx = int(result_num) - 1
    if idx < 0 or idx >= len(chunks_state):
        return f"Result #{int(result_num)} does not exist ({len(chunks_state)} results)."
    source = chunks_state[idx].get('source_file', '')
    if not source:
        return "No file path for this result."
    path = Path(source).resolve()
    if not path.exists():
        return f"File not found: {path}"
    try:
        if sys.platform == 'win32':
            os.startfile(str(path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(path)], check=True)
        else:
            subprocess.run(['xdg-open', str(path)], check=True)
        return f"Opened: {path.name}"
    except Exception as e:
        return f"Could not open file: {e}"


# ---------------------------------------------------------------------------
# Log folder handler
# ---------------------------------------------------------------------------

def open_log_folder() -> str:
    """Open the logs/ directory in the system file explorer."""
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == 'win32':
            os.startfile(str(logs))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(logs)], check=True)
        else:
            subprocess.run(['xdg-open', str(logs)], check=True)
        return f"Opened: {logs}"
    except Exception as e:
        return f"Could not open log folder: {e}"


# ---------------------------------------------------------------------------
# Run summary: parse ingest output + friendly errors
# ---------------------------------------------------------------------------

# (trigger strings, user-facing message)
_ERROR_PATTERNS = [
    (
        ['Word blocked', 'trust', '-2146821993', 'detected a problem'],
        "Word security blocked some files. "
        "Use the **Unblock Sermon Library** button below, then click "
        "**Process New Files** again.",
    ),
    (
        ['Permission denied', 'PermissionError'],
        "Could not access some files — they may be open in another program. "
        "Close any open Word or PowerPoint windows and try again.",
    ),
    (
        ['ModuleNotFoundError', 'ImportError', 'No module named'],
        "A required package is missing. Re-run setup.bat to repair the installation.",
    ),
    (
        ['antiword: not found', "'antiword'"],
        "antiword is not installed. On Linux/WSL run: `sudo apt-get install antiword`",
    ),
]

# Quarantine reasons that count as "skipped" (not errors, not accepted)
_SKIP_OUTCOMES = {
    'too_short', 'non_faith', 'filename_flagged', 'format_pub',
    'worship_slides', 'sparse_pptx', 'duplicates', 'skipped', 'skipped_exists',
}


def _parse_ingest_counts(raw_log: str) -> dict[str, int]:
    """Extract outcome counts from the '--- Ingest Summary ---' block in raw log."""
    import re
    counts: dict[str, int] = {}
    in_summary = False
    for line in raw_log.splitlines():
        if '--- Ingest Summary ---' in line:
            in_summary = True
            continue
        if in_summary:
            m = re.match(r'\s+(\w+)\s+(\d+)', line)
            if m and m.group(1) != 'TOTAL':
                counts[m.group(1)] = int(m.group(2))
    return counts


def _quarantine_filenames(quarantine_root: str, reason: str, limit: int = 10) -> list[str]:
    """Return up to `limit` filenames from a quarantine sub-folder."""
    qdir = Path(_PROJECT_ROOT) / quarantine_root / reason
    if not qdir.exists():
        return []
    names = sorted(p.name for p in qdir.iterdir() if p.is_file())
    return names[:limit]


def _build_run_summary(
    raw_log: str,
    quarantine_root: str = 'raw/quarantine',
    operation: str = 'Processing',
) -> str:
    """Build a human-readable Markdown summary from an ingest+embed run."""
    lines: list[str] = []

    # --- Error patterns take priority ---
    _error_matched = False
    for patterns, message in _ERROR_PATTERNS:
        if any(p in raw_log for p in patterns):
            lines.append(f"⚠️  {message}")
            _error_matched = True
            break
    if not _error_matched and '[exit code:' in raw_log:
        lines.append(
            "⚠️  Something went wrong. "
            "See the technical log below or check **logs/app.log** for details."
        )

    # --- Ingest counts ---
    counts = _parse_ingest_counts(raw_log)
    if counts:
        accepted = counts.get('accepted', 0)
        manual_review = counts.get('manual_review', 0)
        skipped = sum(counts.get(r, 0) for r in _SKIP_OUTCOMES)

        parts: list[str] = []
        if accepted > 0:
            noun = 'sermon' if accepted == 1 else 'sermons'
            parts.append(f"✅  **{accepted}** {noun} added to the archive")
        elif not lines:
            parts.append("ℹ️  No new sermons found.")

        if manual_review > 0:
            noun = 'file' if manual_review == 1 else 'files'
            blocked = _quarantine_filenames(quarantine_root, 'manual_review')
            block_list = '\n'.join(f"  • {f}" for f in blocked)
            total_blocked = counts.get('manual_review', 0)
            overflow = f"\n  *(…and {total_blocked - len(blocked)} more)*" if total_blocked > len(blocked) else ''
            parts.append(
                f"⚠️  **{manual_review}** {noun} need attention "
                f"(Word security blocked):\n{block_list}{overflow}\n\n"
                "Use **Unblock Sermon Library** below, then click **Process New Files** again."
            )

        if skipped > 0:
            noun = 'file' if skipped == 1 else 'files'
            parts.append(
                f"ℹ️  **{skipped}** {noun} skipped "
                "(too short, non-faith content, duplicates, etc.)"
            )

        lines.extend(parts)

    if not lines:
        lines.append(f"✅  {operation} complete.")

    return '\n\n'.join(lines)


# ---------------------------------------------------------------------------
# Unblock handler (Windows only)
# ---------------------------------------------------------------------------

def unblock_library(folder: str) -> tuple[str, str]:
    """Run PowerShell Unblock-File on all files in the sermon library folder.

    Returns (summary, raw_log). Only meaningful on Windows; shows a clear
    message on other platforms.
    """
    if not folder or not folder.strip():
        return "Please enter your sermon library folder path first.", ""
    folder = folder.strip()
    if not Path(folder).is_dir():
        return f"Folder not found: {folder}", ""

    if sys.platform != 'win32':
        return "ℹ️  Unblock-File is a Windows-only operation.", ""

    raw = f"=== Unblocking files in: {folder} ===\n\n"
    cmd = [
        'powershell', '-NoProfile', '-NonInteractive', '-Command',
        f'Get-ChildItem -Path "{folder}" -Recurse -File | Unblock-File -Confirm:$false; '
        f'Write-Output "Done."',
    ]
    _log = get_logger(__name__)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=_PROJECT_ROOT
        )
        raw += result.stdout
        if result.stderr:
            raw += '\n[stderr]\n' + result.stderr
        if result.returncode != 0:
            raw += f'\n[exit code: {result.returncode}]'
            _log.error('Unblock-File exited %d\n%s', result.returncode, raw)
            summary = '⚠️  Unblock command finished with errors. See the technical log.'
        else:
            summary = (
                '✅  Files unblocked successfully.\n\n'
                'Click **Process New Files** to retry ingesting the blocked sermons.'
            )
    except Exception as e:
        _log.error('Unblock-File failed', exc_info=True)
        raw += f'Error: {e}'
        summary = f'⚠️  Could not run PowerShell: {e}'

    return summary, raw


# ---------------------------------------------------------------------------
# Folder picker (Windows: tkinter subprocess; other: no-op)
# ---------------------------------------------------------------------------

def browse_folder() -> str:
    """Open a native folder picker dialog and return the selected path.

    Runs tkinter in a subprocess to avoid GUI/thread conflicts with Gradio.
    Returns '' on cancel or if tkinter is unavailable.
    """
    if sys.platform != 'win32':
        return ''
    try:
        result = subprocess.run(
            [
                sys.executable, '-c',
                'import tkinter as tk; from tkinter import filedialog; '
                'root = tk.Tk(); root.withdraw(); root.wm_attributes("-topmost", 1); '
                'path = filedialog.askdirectory(title="Select your sermon library folder"); '
                'print(path, end="")',
            ],
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# Manage Archive handlers
# ---------------------------------------------------------------------------

def _run_subprocess(cmd: list[str]) -> str:
    """Run a subprocess, capture stdout+stderr, return combined output."""
    _log = get_logger(__name__)
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=_PROJECT_ROOT,
            env=env,
        )
        out = result.stdout
        if result.stderr:
            out += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            out += f"\n[exit code: {result.returncode}]"
            _log.error("Subprocess exited %d: %s\n%s", result.returncode, cmd, out)
        return out
    except Exception as e:
        _log.error("Subprocess launch failed: %s", cmd, exc_info=True)
        return f"Subprocess error: {e}"


def _validate_and_persist_folder(folder: str) -> tuple[str, str] | None:
    """Validate folder path and persist it. Returns (None, None) on success,
    or (summary, raw_log) error tuple on failure."""
    if not folder or not folder.strip():
        msg = "Please enter your sermon library folder path."
        return msg, ""
    folder = folder.strip()
    if not Path(folder).is_dir():
        msg = (
            f"Folder not found: {folder}\n\n"
            "Check that the path is correct and the drive is connected, then try again."
        )
        return msg, ""
    settings = load_settings()
    settings['sermon_library_folder'] = folder
    save_settings(settings)
    return None, None


def process_new_files(folder: str) -> tuple[str, str]:
    """Ingest + incremental embed. Returns (summary, raw_log)."""
    err_summary, err_log = _validate_and_persist_folder(folder)
    if err_summary is not None:
        return err_summary, err_log

    folder = folder.strip()
    raw = f"=== Processing new files from: {folder} ===\n\n"
    raw += "--- Step 1: Ingest files ---\n"
    raw += _run_subprocess([sys.executable, "build/01_ingest_files.py", "--source", folder, "--verbose"])
    raw += "\n\n--- Step 2: Incremental embed ---\n"
    raw += _run_subprocess([sys.executable, "build/02_chunk_embed.py", "--incremental"])

    raw += "\n\n--- Reloading retriever ---\n"
    try:
        from app.retriever import load_retriever
        global _retriever
        _retriever = load_retriever(
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH,
            sermon_root=folder.strip(),
        )
        raw += "Retriever reloaded successfully.\n"
    except Exception as e:
        raw += f"Retriever reload failed: {e}\n"
        get_logger(__name__).error("Retriever reload failed", exc_info=True)

    summary = _build_run_summary(raw, operation='Processing')
    return summary, raw


def full_rebuild(folder: str) -> tuple[str, str]:
    """Full ingest (force) + full embed rebuild. Returns (summary, raw_log)."""
    err_summary, err_log = _validate_and_persist_folder(folder)
    if err_summary is not None:
        return err_summary, err_log

    folder = folder.strip()
    raw = f"=== Full rebuild from: {folder} ===\n\n"
    raw += "--- Step 1: Ingest files (force) ---\n"
    raw += _run_subprocess([
        sys.executable, "build/01_ingest_files.py",
        "--source", folder, "--force", "--verbose",
    ])
    raw += "\n\n--- Step 2: Full embed rebuild ---\n"
    raw += _run_subprocess([sys.executable, "build/02_chunk_embed.py", "--force"])

    raw += "\n\n--- Reloading retriever ---\n"
    try:
        from app.retriever import load_retriever
        global _retriever
        _retriever = load_retriever(
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH,
            sermon_root=folder,
        )
        raw += "Retriever reloaded successfully.\n"
    except Exception as e:
        raw += f"Retriever reload failed: {e}\n"
        get_logger(__name__).error("Retriever reload failed", exc_info=True)

    summary = _build_run_summary(raw, operation='Rebuild')
    return summary, raw


# ---------------------------------------------------------------------------
# Quarantine management handlers
# ---------------------------------------------------------------------------

def _quarantine_root() -> Path:
    return Path(_PROJECT_ROOT) / QUARANTINE_ROOT


def list_quarantine() -> dict[str, list[str]]:
    """Return {reason: [filename, ...]} for every file in every quarantine bucket.

    Keys are ordered by descending file count so the most important bucket
    (manual_review) is always first in the UI.
    """
    root = _quarantine_root()
    buckets: dict[str, list[str]] = {}
    if not root.exists():
        return buckets
    for sub in sorted(root.iterdir()):
        if sub.is_dir():
            files = sorted(f.name for f in sub.iterdir() if f.is_file())
            if files:
                buckets[sub.name] = files
    # Sort by descending count
    return dict(sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True))


def ignore_quarantine_file(reason: str, filename: str) -> str:
    """Permanently delete a file from its quarantine bucket (mark as ignored)."""
    p = _quarantine_root() / reason / filename
    if not p.exists():
        return f"Already removed: {filename}"
    try:
        p.unlink()
        return f"Ignored and removed: {filename}"
    except Exception as e:
        get_logger(__name__).error("Could not remove quarantine file %s: %s", p, e)
        return f"Error removing {filename}: {e}"


def force_ingest_file(reason: str, filename: str) -> str:
    """Move a quarantined file into the user's sermon library folder and re-ingest it.

    For manual_review (.doc) files this also runs Unblock-File first so Word
    COM can open them.  For all other reasons the file is simply moved to the
    library root and processed via --force.
    """
    _log = get_logger(__name__)
    src = _quarantine_root() / reason / filename
    if not src.exists():
        return f"File not found in quarantine: {filename}"

    settings = load_settings()
    library = settings.get('sermon_library_folder', '').strip()
    if not library or not Path(library).is_dir():
        return (
            "Sermon library folder is not set or does not exist. "
            "Set it on the Manage Archive tab first."
        )

    dest = Path(library) / filename
    # Avoid clobbering an existing file
    if dest.exists():
        stem = src.stem
        suffix = src.suffix
        dest = Path(library) / f"{stem}_recovered{suffix}"

    try:
        import shutil
        shutil.copy2(str(src), str(dest))
    except Exception as e:
        _log.error("Could not copy %s → %s: %s", src, dest, e)
        return f"Could not copy file: {e}"

    lines = [f"Copied {filename} → {dest.name}"]

    # Unblock on Windows before ingest (critical for .doc files)
    if sys.platform == 'win32':
        unblock_result = _run_subprocess([
            'powershell', '-NonInteractive', '-Command',
            f'Unblock-File -Path "{dest}"',
        ])
        if 'error' in unblock_result.lower():
            lines.append(f"Unblock warning: {unblock_result.strip()}")
        else:
            lines.append("Unblocked successfully.")

    # Re-ingest just this one file using the library as source
    raw = _run_subprocess([
        sys.executable, "build/01_ingest_files.py",
        "--source", library, "--force", "--verbose",
        "--limit", "0",   # no limit — but only new/forced files are touched
    ])
    lines.append("\n--- Ingest output ---")
    lines.append(raw.strip())

    # Incremental embed
    raw2 = _run_subprocess([sys.executable, "build/02_chunk_embed.py", "--incremental"])
    lines.append("\n--- Embed output ---")
    lines.append(raw2.strip())

    # Reload retriever
    try:
        from app.retriever import load_retriever
        global _retriever
        _retriever = load_retriever(
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH,
            sermon_root=library,
        )
        lines.append("\nRetriever reloaded.")
    except Exception as e:
        lines.append(f"\nRetriever reload failed: {e}")

    # Remove from quarantine now that it's been processed
    try:
        src.unlink()
        lines.append(f"Removed from quarantine/{reason}/.")
    except Exception:
        pass

    return "\n".join(lines)


def get_quarantine_summary() -> str:
    """Return a Markdown summary of quarantine bucket counts."""
    buckets = list_quarantine()
    if not buckets:
        return "_No files in quarantine — everything has been processed._"
    total = sum(len(v) for v in buckets.values())
    lines = [f"**{total} file(s) in quarantine** across {len(buckets)} bucket(s).\n"]
    for reason, files in buckets.items():
        label = QUARANTINE_LABELS.get(reason, reason)
        lines.append(f"- **{label}**: {len(files)} file(s)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

CSS = """
/* ── Overall container ───────────────────────────────────────────────── */
.gradio-container {
    font-family: Georgia, 'Times New Roman', serif;
    background-color: #f9f7f4;
}

/* ── App header ──────────────────────────────────────────────────────── */
#app-header {
    text-align: center;
    padding: 0.75rem 0 1.25rem;
    border-bottom: 1px solid #e4ddd4;
    margin-bottom: 1rem;
}

/* ── Search: answer box ──────────────────────────────────────────────── */
.answer-box {
    background: #ffffff;
    border-left: 4px solid #8b5e3c;
    border-radius: 0 6px 6px 0;
    padding: 1rem 1.5rem;
    line-height: 1.8;
    color: #2a1f17;
    min-height: 2.5rem;
}
.answer-box p { margin: 0; }

/* ── Search: results table ───────────────────────────────────────────── */
.passages-table { font-size: 0.85rem; }
.passages-table table th {
    background-color: #f0ebe3 !important;
    color: #3b2a1e !important;
    font-weight: 600;
}

/* ── Shared hint / status text ───────────────────────────────────────── */
.status-hint { color: #9a8070; font-size: 0.82rem; }

/* ── Archive: section dividers ───────────────────────────────────────── */
.archive-divider {
    border: none;
    border-top: 1px solid #e4ddd4;
    margin: 1.25rem 0;
}

footer { display: none !important; }
"""


def build_ui():
    import gradio as gr

    # Load persisted settings for default values
    _settings = load_settings()
    _saved_folder = _settings.get('sermon_library_folder', '')

    with gr.Blocks(title="Sermon Note Search", theme=gr.themes.Soft(), css=CSS) as demo:

        # ── App header ────────────────────────────────────────────────────
        gr.HTML("""
            <div id="app-header">
                <h1 style="font-family:Georgia,serif;font-size:1.9rem;font-weight:normal;
                           color:#3b2a1e;letter-spacing:0.02em;margin:0 0 0.3rem">
                    Sermon Note Search
                </h1>
                <p style="color:#9a8070;font-size:0.88rem;margin:0">
                    Private &amp; offline — your notes never leave this computer
                </p>
            </div>
        """)

        with gr.Tabs():

            # ----------------------------------------------------------------
            # Search tab
            # ----------------------------------------------------------------
            with gr.Tab("🔍  Search"):
                chunks_state = gr.State([])

                # Full-width query box
                query_box = gr.Textbox(
                    label="",
                    show_label=False,
                    lines=2,
                    max_lines=6,
                    placeholder=(
                        "Ask about a topic, scripture, or season…\n"
                        "e.g. 'forgiveness in the Psalms'  ·  'Advent 2012'  ·  'prodigal son'"
                    ),
                )

                # Search button + Min. results slider on the same row
                with gr.Row():
                    search_btn = gr.Button("Search", variant="primary", scale=3)
                    top_k_slider = gr.Slider(
                        minimum=1,
                        maximum=MAX_TOP_K,
                        value=TOP_K,
                        step=1,
                        label="Min. results",
                        scale=1,
                    )

                # Answer — shows a soft hint before the first search
                answer_md = gr.Markdown(
                    value="_Enter a topic, scripture, or sermon theme above to search your notes._",
                    elem_classes=["answer-box"],
                )

                gr.HTML("<hr class='archive-divider'>")

                results_df = gr.Dataframe(
                    headers=["#", "Title", "Scripture", "Date", "Excerpt", "Match %", "Source File"],
                    datatype=["number", "str", "str", "str", "str", "str", "str"],
                    label="Matching Passages  —  click a row to open the source file",
                    wrap=True,
                    elem_classes=["passages-table"],
                    row_count=(MAX_TOP_K, "fixed"),
                )

                with gr.Row():
                    result_num = gr.Number(
                        value=1, minimum=1, maximum=MAX_TOP_K, step=1,
                        label="Row", scale=1,
                    )
                    open_btn = gr.Button("📖  Open File", scale=2)
                    open_status = gr.Textbox(
                        label="", interactive=False, show_label=False,
                        placeholder="Click a row in the table, or enter a row number and click Open File",
                        scale=4,
                    )

                status_md = gr.Markdown(value="", elem_classes=["status-hint"])

                # Search events
                search_inputs = [query_box, top_k_slider]
                search_outputs = [answer_md, results_df, status_md, chunks_state]
                search_btn.click(fn=handle_query, inputs=search_inputs, outputs=search_outputs)
                query_box.submit(fn=handle_query, inputs=search_inputs, outputs=search_outputs)

                # Slider change — re-slice cached results without a new search
                top_k_slider.change(
                    fn=expand_results,
                    inputs=[top_k_slider, chunks_state],
                    outputs=[results_df, status_md],
                )

                # Row-click file open (best-effort — depends on Gradio build)
                results_df.select(fn=on_row_select, inputs=[chunks_state], outputs=[open_status])
                # Reliable fallback: Row number input + button
                open_btn.click(fn=open_file, inputs=[result_num, chunks_state], outputs=[open_status])

            # ----------------------------------------------------------------
            # Quarantine tab
            # ----------------------------------------------------------------
            with gr.Tab("⚠️  Quarantine"):

                gr.HTML("""
                    <h3 style="font-family:Georgia,serif;font-weight:normal;
                               color:#3b2a1e;margin:0.5rem 0 0.25rem">
                        Quarantined Files
                    </h3>
                """)
                gr.Markdown(
                    "These files were set aside during indexing. "
                    "You can **Force Ingest** a file to move it into your library and index it, "
                    "or **Ignore** it to remove it from this list permanently.",
                    elem_classes=["status-hint"],
                )

                with gr.Row():
                    quarantine_refresh_btn = gr.Button("🔄  Refresh", variant="secondary", scale=1)
                    quarantine_summary_md = gr.Markdown(
                        value=get_quarantine_summary(), scale=4
                    )

                gr.HTML("<hr class='archive-divider'>")

                quarantine_action_md = gr.Markdown(value="")

                # One accordion per quarantine bucket, populated at render time
                _buckets = list_quarantine()
                for _reason, _files in _buckets.items():
                    _label = QUARANTINE_LABELS.get(_reason, _reason)
                    _count = len(_files)
                    with gr.Accordion(
                        f"{_label}  ({_count} file{'s' if _count != 1 else ''})",
                        open=(_reason == 'manual_review'),
                    ):
                        if _reason == 'manual_review':
                            gr.Markdown(
                                "💡 These `.doc` files are blocked by Windows security. "
                                "**Force Ingest** will unblock and index the file. "
                                "Or run **Unblock Sermon Library** on the Manage Archive tab "
                                "to unblock all files at once, then Process New Files.",
                                elem_classes=["status-hint"],
                            )

                        # Show up to 200 files per bucket to keep the UI responsive
                        _visible = _files[:200]
                        if len(_files) > 200:
                            gr.Markdown(
                                f"_Showing first 200 of {len(_files)} files. "
                                "Unblock + Process New Files is the fastest way to handle large batches._",
                                elem_classes=["status-hint"],
                            )

                        for _fname in _visible:
                            with gr.Row():
                                gr.Textbox(
                                    value=_fname, interactive=False, show_label=False,
                                    scale=5, lines=1, max_lines=1,
                                )
                                _fi_btn = gr.Button(
                                    "➕ Force Ingest", scale=1, variant="primary",
                                    size="sm",
                                )
                                _ig_btn = gr.Button(
                                    "✕ Ignore", scale=1, variant="secondary",
                                    size="sm",
                                )
                                # Capture loop vars in closures
                                _fi_btn.click(
                                    fn=lambda r=_reason, f=_fname: force_ingest_file(r, f),
                                    inputs=[],
                                    outputs=[quarantine_action_md],
                                )
                                _ig_btn.click(
                                    fn=lambda r=_reason, f=_fname: ignore_quarantine_file(r, f),
                                    inputs=[],
                                    outputs=[quarantine_action_md],
                                )

                quarantine_refresh_btn.click(
                    fn=get_quarantine_summary,
                    inputs=[],
                    outputs=[quarantine_summary_md],
                )

            # ----------------------------------------------------------------
            # Manage Archive tab
            # ----------------------------------------------------------------
            with gr.Tab("📁  Manage Archive"):

                # ── Section: Library folder ───────────────────────────────
                gr.HTML("""
                    <h3 style="font-family:Georgia,serif;font-weight:normal;
                               color:#3b2a1e;margin:0.5rem 0 0.4rem">
                        Sermon Library Folder
                    </h3>
                """)
                gr.Markdown(
                    "Set this to the folder where all your sermon files live. "
                    "Add new files there first, then click **Process New Files** to index them.",
                    elem_classes=["status-hint"],
                )

                with gr.Row():
                    folder_box = gr.Textbox(
                        label="",
                        show_label=False,
                        placeholder=r"e.g. C:\Sermons  or  E:\Ministry\Sermons",
                        value=_saved_folder,
                        lines=1,
                        scale=5,
                    )
                    if sys.platform == 'win32':
                        browse_btn = gr.Button("📁  Browse…", scale=1)

                # ── Section: Update index ─────────────────────────────────
                gr.HTML("<hr class='archive-divider'>")
                gr.HTML("""
                    <h3 style="font-family:Georgia,serif;font-weight:normal;
                               color:#3b2a1e;margin:0 0 0.4rem">
                        Update Search Index
                    </h3>
                """)
                gr.Markdown(
                    "_Use **Process New Files** for day-to-day additions. "
                    "**Full Rebuild** only if search results seem wrong or incomplete._",
                    elem_classes=["status-hint"],
                )

                with gr.Row():
                    process_btn = gr.Button("➕  Process New Files", variant="primary")
                    rebuild_btn = gr.Button("🔄  Full Rebuild", variant="secondary")

                archive_summary = gr.Markdown(value="")

                with gr.Accordion("Technical log", open=False):
                    archive_log = gr.Textbox(
                        label="",
                        show_label=False,
                        interactive=False,
                        lines=12,
                        max_lines=20,
                    )

                # ── Section: File security ────────────────────────────────
                gr.HTML("<hr class='archive-divider'>")
                gr.HTML("""
                    <h3 style="font-family:Georgia,serif;font-weight:normal;
                               color:#3b2a1e;margin:0 0 0.4rem">
                        File Security
                    </h3>
                """)
                gr.Markdown(
                    "If Word is blocking `.doc` files, click **Unblock Sermon Library** "
                    "to remove Windows' security flag from every file in your library. "
                    "*Only use this on folders you fully trust.*",
                    elem_classes=["status-hint"],
                )
                unblock_btn = gr.Button("🔓  Unblock Sermon Library", variant="secondary")

                # ── Section: Diagnostics ──────────────────────────────────
                gr.HTML("<hr class='archive-divider'>")
                with gr.Row():
                    log_btn = gr.Button("📂  Open Log Folder", variant="secondary")
                    log_status = gr.Textbox(
                        label="", interactive=False, show_label=False,
                        placeholder="Application logs are saved to the logs/ folder",
                        scale=4,
                    )

                # Event wiring (unchanged)
                archive_outputs = [archive_summary, archive_log]
                process_btn.click(fn=process_new_files, inputs=[folder_box], outputs=archive_outputs)
                rebuild_btn.click(fn=full_rebuild, inputs=[folder_box], outputs=archive_outputs)
                unblock_btn.click(fn=unblock_library, inputs=[folder_box], outputs=archive_outputs)
                log_btn.click(fn=open_log_folder, inputs=[], outputs=[log_status])
                if sys.platform == 'win32':
                    browse_btn.click(fn=browse_folder, inputs=[], outputs=[folder_box])

    return demo


# ---------------------------------------------------------------------------
# CLI + entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Gradio UI for AI-Powered Sermon Note Search.')
    p.add_argument('--host',  metavar='STR', default='127.0.0.1',
                   help='Bind address (default: 127.0.0.1 — local only)')
    p.add_argument('--port',  metavar='INT', type=int, default=7860)
    p.add_argument('--db',    metavar='PATH', default=DB_PATH)
    p.add_argument('--faiss', metavar='PATH', default=FAISS_PATH)
    p.add_argument('--idmap', metavar='PATH', default=ID_MAP_PATH)
    p.add_argument('--model', metavar='PATH', default=MODEL_PATH)
    return p


def main() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    print("Loading retriever and LLM...")
    ret_status, llm_status = _load_components(
        db=args.db,
        faiss=args.faiss,
        idmap=args.idmap,
        model=args.model,
    )
    print(ret_status)
    print(llm_status)

    demo = build_ui()
    # inbrowser=True opens the browser only after Gradio's server is ready,
    # avoiding the "Site Not Found" error on slow machines.
    # share=False (default) keeps the app strictly local — no public Gradio tunnel.
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=False,
        inbrowser=True,
    )


if __name__ == '__main__':
    main()
