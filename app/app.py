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
    DB_PATH,
    FAISS_PATH,
    ID_MAP_PATH,
    LOW_CONFIDENCE_THRESHOLD,
    MAX_TOP_K,
    MODEL_PATH,
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
        _retriever = load_retriever(db_path=db, faiss_path=faiss, idmap_path=idmap)
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

def handle_query(query: str, top_k: int = TOP_K):
    """Search handler — returns (answer, dataframe_rows, status, chunks_state).

    chunks_state is stored in a gr.State so the row-click handler can access it.
    """
    empty = ("Please enter a question.", [], "No query.", [])

    if not query or not query.strip():
        return empty

    if _retriever is None:
        return ("Retriever is not available. Check startup logs.", [], "Error: retriever not loaded", [])

    try:
        chunks = _retriever.search(query, top_k=int(top_k))
    except Exception as e:
        return (f"Retrieval error: {e}", [], f"Error: {e}", [])

    if not chunks:
        return ("No relevant sermons found for this query.", [], "0 results", [])

    # Build answer via LLM (or fallback if LLM not loaded)
    if _llm is not None:
        try:
            answer = _llm.generate(query, chunks)
        except Exception as e:
            answer = f"(LLM error: {e})\n\nTop result: {chunks[0].get('text', '')[:300]}"
    else:
        top = chunks[0]
        answer = (
            f"**Note:** LLM not loaded — showing top match only.\n\n"
            f"**{top.get('title', '(untitled)')}** "
            f"({top.get('scripture_ref', '')})\n\n"
            f"{top.get('text', '')[:500]}..."
        )

    # Theoretical max RRF score: two lists each contribute 1/(RRF_K+1)
    RRF_MAX = 2.0 / 61.0
    max_score = max(c.get('score', 0) for c in chunks)

    # Build dataframe rows — display basename for Source File column
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

    if max_score < LOW_CONFIDENCE_THRESHOLD:
        status = (
            f"⚠️ Low confidence ({max_score:.3f}) — "
            "this topic may not be in your archive. "
            "Results shown are the closest matches available."
        )
    else:
        status = f"{len(chunks)} result(s) returned"

    return answer, rows, status, chunks


# ---------------------------------------------------------------------------
# Row-click file open handler
# ---------------------------------------------------------------------------

def _extract_row_index(evt) -> int | None:
    """Extract the clicked row index from whatever Gradio passes to a select handler.

    Gradio 5.x passes SelectData (has .index attribute).
    Some builds pass a plain (row, col) tuple of ints.
    If neither is detected (e.g. full dataframe value passed), returns None.
    """
    # Standard: SelectData with .index = [row, col] or just row int
    if hasattr(evt, 'index'):
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
# Friendly error parsing
# ---------------------------------------------------------------------------

# (pattern, user-facing message)
_ERROR_PATTERNS = [
    (
        ['Word blocked', 'trust', '-2146821993', 'detected a problem'],
        "Word security blocked some files.\n"
        "Fix: add your sermon folder to Word Trusted Locations, or use the "
        "'Unblock Sermon Library' button (Tier 2), then click Process New Files again.",
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
        "antiword is not installed. On Linux/WSL run: sudo apt-get install antiword",
    ),
]


def _friendly_summary(raw_log: str) -> str:
    """Return a plain-English summary line if a known error pattern is found."""
    for patterns, message in _ERROR_PATTERNS:
        if any(p in raw_log for p in patterns):
            return f"⚠️  {message}"
    if '[exit code:' in raw_log:
        return (
            "⚠️  Something went wrong during processing. "
            "See the technical log below or check logs/app.log for details."
        )
    return ""


# ---------------------------------------------------------------------------
# Manage Archive handlers
# ---------------------------------------------------------------------------

def _run_subprocess(cmd: list[str]) -> str:
    """Run a subprocess, capture stdout+stderr, return combined output."""
    _log = get_logger(__name__)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
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
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH
        )
        raw += "Retriever reloaded successfully.\n"
    except Exception as e:
        raw += f"Retriever reload failed: {e}\n"
        get_logger(__name__).error("Retriever reload failed", exc_info=True)

    summary = _friendly_summary(raw) or "✅  Processing complete."
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
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH
        )
        raw += "Retriever reloaded successfully.\n"
    except Exception as e:
        raw += f"Retriever reload failed: {e}\n"
        get_logger(__name__).error("Retriever reload failed", exc_info=True)

    summary = _friendly_summary(raw) or "✅  Rebuild complete."
    return summary, raw


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

CSS = """
#search-col { max-width: 860px; margin: auto; }
.answer-box { background: #f8f8f5; border-radius: 8px; padding: 1rem; }
.results-table { font-size: 0.88rem; }
footer { display: none !important; }
"""


def build_ui():
    import gradio as gr

    # Load persisted settings for default values
    _settings = load_settings()
    _saved_folder = _settings.get('sermon_library_folder', '')

    with gr.Blocks(title="Sermon Note Search", theme=gr.themes.Soft(), css=CSS) as demo:
        gr.Markdown("# Sermon Note Search")

        with gr.Tabs():

            # ----------------------------------------------------------------
            # Search tab
            # ----------------------------------------------------------------
            with gr.Tab("Search"):
                chunks_state = gr.State([])

                with gr.Row(elem_id="search-col"):
                    query_box = gr.Textbox(
                        label="Your question",
                        lines=1,
                        max_lines=6,
                        placeholder="Ask about a topic, scripture, or season…",
                        scale=4,
                    )
                    top_k_slider = gr.Slider(
                        minimum=1,
                        maximum=MAX_TOP_K,
                        value=TOP_K,
                        step=1,
                        label="Results",
                        scale=1,
                    )

                search_btn = gr.Button("Search", variant="primary")

                answer_md = gr.Markdown(
                    label="Answer",
                    value="",
                    elem_classes=["answer-box"],
                )

                gr.HTML("<hr style='border:none;border-top:1px solid #ddd;margin:0.5rem 0'>")

                results_df = gr.Dataframe(
                    headers=["#", "Title", "Scripture", "Date", "Snippet", "Match %", "Source File"],
                    datatype=["number", "str", "str", "str", "str", "str", "str"],
                    label="Source Chunks  (click a row to open the file)",
                    wrap=True,
                    elem_classes=["results-table"],
                    row_count=(15, "fixed"),
                )

                with gr.Row():
                    result_num = gr.Number(
                        value=1, minimum=1, maximum=MAX_TOP_K, step=1,
                        label="Result #", scale=1,
                    )
                    open_btn = gr.Button("Open File", scale=2)
                    open_status = gr.Textbox(
                        label="", interactive=False, show_label=False,
                        placeholder="Click a row or enter Result # and click Open File…",
                        scale=4,
                    )

                status_md = gr.Markdown(value="")

                # Search events
                search_inputs = [query_box, top_k_slider]
                search_outputs = [answer_md, results_df, status_md, chunks_state]
                search_btn.click(fn=handle_query, inputs=search_inputs, outputs=search_outputs)
                query_box.submit(fn=handle_query, inputs=search_inputs, outputs=search_outputs)

                # Row-click file open (best-effort — depends on Gradio build)
                results_df.select(fn=on_row_select, inputs=[chunks_state], outputs=[open_status])
                # Reliable fallback: Result # number input + button
                open_btn.click(fn=open_file, inputs=[result_num, chunks_state], outputs=[open_status])

            # ----------------------------------------------------------------
            # Manage Archive tab
            # ----------------------------------------------------------------
            with gr.Tab("Manage Archive"):
                gr.Markdown(
                    "### Sermon library folder\n"
                    "Set this to your **main sermon library folder** — the single folder "
                    "(or folder tree) where all your sermon files live. "
                    "Add new sermon files into that folder first, then click "
                    "**Process New Files** to index them."
                )

                folder_box = gr.Textbox(
                    label="Sermon library folder",
                    placeholder=r"e.g. C:\Sermons  or  E:\Ministry\Sermons",
                    value=_saved_folder,
                    lines=1,
                )

                with gr.Row():
                    process_btn = gr.Button("➕ Process New Files", variant="primary")
                    rebuild_btn = gr.Button("🔄 Full Rebuild", variant="secondary")

                archive_summary = gr.Markdown(value="")

                with gr.Accordion("Technical log", open=False):
                    archive_log = gr.Textbox(
                        label="",
                        show_label=False,
                        interactive=False,
                        lines=12,
                        max_lines=20,
                    )

                with gr.Row():
                    log_btn = gr.Button("📂 Open Log Folder", variant="secondary")
                    log_status = gr.Textbox(
                        label="", interactive=False, show_label=False,
                        placeholder="Log files are saved to logs/app.log",
                        scale=4,
                    )

                archive_outputs = [archive_summary, archive_log]
                process_btn.click(fn=process_new_files, inputs=[folder_box], outputs=archive_outputs)
                rebuild_btn.click(fn=full_rebuild, inputs=[folder_box], outputs=archive_outputs)
                log_btn.click(fn=open_log_folder, inputs=[], outputs=[log_status])

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
