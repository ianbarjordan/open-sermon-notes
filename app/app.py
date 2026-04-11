"""
app.py — Gradio UI for AI-Powered Sermon Note Search.

Usage:
    python app/app.py --port 7860
    python app/app.py --host 0.0.0.0 --port 7860 --share
"""
import argparse
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
    TOP_K,
)

# ---------------------------------------------------------------------------
# Global retriever + LLM (loaded once at startup)
# ---------------------------------------------------------------------------
_retriever = None
_llm = None

# Project root (parent of app/)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _load_components(
    db: str,
    faiss: str,
    idmap: str,
    model: str,
) -> tuple[str, str]:
    """Load retriever and LLM; return (retriever_status, llm_status)."""
    global _retriever, _llm

    ret_status = "Retriever: not loaded"
    llm_status = "LLM: not loaded"

    try:
        from app.retriever import load_retriever
        _retriever = load_retriever(db_path=db, faiss_path=faiss, idmap_path=idmap)
        ret_status = "Retriever: loaded"
    except Exception as e:
        ret_status = f"Retriever ERROR: {e}"
        print(ret_status, file=sys.stderr)

    try:
        from app.llm import load_llm
        _llm = load_llm(model_path=model)
        llm_status = "LLM: loaded"
    except FileNotFoundError as e:
        llm_status = f"LLM: model not found — {e}"
        print(llm_status, file=sys.stderr)
    except Exception as e:
        llm_status = f"LLM ERROR: {e}"
        print(llm_status, file=sys.stderr)

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

def on_row_select(evt, chunks_state: list) -> str:
    """Fires when any cell in results_df is clicked. Opens source file for that row."""
    if evt is None:
        return ""
    row_index = evt.index[0]
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
# Manage Archive handlers
# ---------------------------------------------------------------------------

def _run_subprocess(cmd: list[str]) -> str:
    """Run a subprocess, capture stdout+stderr, return combined output."""
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
        return out
    except Exception as e:
        return f"Subprocess error: {e}"


def process_new_files(folder: str) -> str:
    """Ingest + incremental embed for a new folder of sermon files."""
    if not folder or not folder.strip():
        return "Please enter a folder path."

    log = f"=== Processing new files from: {folder} ===\n\n"

    log += "--- Step 1: Ingest files ---\n"
    log += _run_subprocess([sys.executable, "build/01_ingest_files.py", "--source", folder, "--verbose"])
    log += "\n\n--- Step 2: Incremental embed ---\n"
    log += _run_subprocess([sys.executable, "build/02_chunk_embed.py", "--incremental"])

    # Reload retriever in-place
    log += "\n\n--- Reloading retriever ---\n"
    try:
        from app.retriever import load_retriever
        global _retriever
        _retriever = load_retriever(
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH
        )
        log += "Retriever reloaded successfully.\n"
    except Exception as e:
        log += f"Retriever reload failed: {e}\n"

    return log


def full_rebuild(folder: str) -> str:
    """Full ingest (force) + full embed rebuild."""
    if not folder or not folder.strip():
        return "Please enter a folder path."

    log = f"=== Full rebuild from: {folder} ===\n\n"

    log += "--- Step 1: Ingest files (force) ---\n"
    log += _run_subprocess([
        sys.executable, "build/01_ingest_files.py",
        "--source", folder, "--force", "--verbose",
    ])
    log += "\n\n--- Step 2: Full embed rebuild ---\n"
    log += _run_subprocess([sys.executable, "build/02_chunk_embed.py", "--force"])

    # Reload retriever in-place
    log += "\n\n--- Reloading retriever ---\n"
    try:
        from app.retriever import load_retriever
        global _retriever
        _retriever = load_retriever(
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH
        )
        log += "Retriever reloaded successfully.\n"
    except Exception as e:
        log += f"Retriever reload failed: {e}\n"

    return log


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
                        lines=3,
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
                )

                open_status = gr.Textbox(
                    label="",
                    interactive=False,
                    show_label=False,
                    placeholder="Click a result row to open the file…",
                )

                status_md = gr.Markdown(value="")

                # Search events
                search_inputs = [query_box, top_k_slider]
                search_outputs = [answer_md, results_df, status_md, chunks_state]
                search_btn.click(fn=handle_query, inputs=search_inputs, outputs=search_outputs)
                query_box.submit(fn=handle_query, inputs=search_inputs, outputs=search_outputs)

                # Row-click file open
                results_df.select(fn=on_row_select, inputs=[chunks_state], outputs=[open_status])

            # ----------------------------------------------------------------
            # Manage Archive tab
            # ----------------------------------------------------------------
            with gr.Tab("Manage Archive"):
                gr.Markdown(
                    "### Add or rebuild the sermon archive\n"
                    "Enter the path to a folder containing new sermon files, "
                    "then choose an action."
                )

                folder_box = gr.Textbox(
                    label="New sermon files folder",
                    placeholder=r"e.g. C:\Sermons\2025  or  ./new_sermons",
                    lines=1,
                )

                with gr.Row():
                    process_btn = gr.Button("➕ Process New Files", variant="primary")
                    rebuild_btn = gr.Button("🔄 Full Rebuild", variant="secondary")

                archive_log = gr.Textbox(
                    label="Output log",
                    interactive=False,
                    lines=12,
                    max_lines=20,
                )

                process_btn.click(fn=process_new_files, inputs=[folder_box], outputs=[archive_log])
                rebuild_btn.click(fn=full_rebuild, inputs=[folder_box], outputs=[archive_log])

    return demo


# ---------------------------------------------------------------------------
# CLI + entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Gradio UI for AI-Powered Sermon Note Search.')
    p.add_argument('--host',  metavar='STR', default='127.0.0.1')
    p.add_argument('--port',  metavar='INT', type=int, default=7860)
    p.add_argument('--share', action='store_true', help='Create a public Gradio share link')
    p.add_argument('--db',    metavar='PATH', default=DB_PATH)
    p.add_argument('--faiss', metavar='PATH', default=FAISS_PATH)
    p.add_argument('--idmap', metavar='PATH', default=ID_MAP_PATH)
    p.add_argument('--model', metavar='PATH', default=MODEL_PATH)
    return p


def main() -> None:
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
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
    )


if __name__ == '__main__':
    main()
