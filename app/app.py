"""
app.py — Gradio UI for AI-Powered Sermon Note Search.

Usage:
    python app/app.py --port 7860
    python app/app.py --host 0.0.0.0 --port 7860 --share
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import DB_PATH, FAISS_PATH, ID_MAP_PATH, LOW_CONFIDENCE_THRESHOLD, MODEL_PATH  # noqa: E402

# ---------------------------------------------------------------------------
# Global retriever + LLM (loaded once at startup)
# ---------------------------------------------------------------------------
_retriever = None
_llm = None


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

def handle_query(query: str):
    """Search handler — returns (answer, dataframe_rows, status, chunks_state).

    chunks_state is stored in a gr.State so the Open File handler can access it.
    """
    empty = ("Please enter a question.", [], "No query.", [])

    if not query or not query.strip():
        return empty

    if _retriever is None:
        return ("Retriever is not available. Check startup logs.", [], "Error: retriever not loaded", [])

    try:
        chunks = _retriever.search(query)
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

    # Build dataframe rows
    rows = []
    for i, c in enumerate(chunks):
        snippet = (c.get('text') or '')[:120] + '...'
        match_pct = f"{min(c.get('score', 0) / RRF_MAX * 100, 100):.0f}%"
        rows.append([
            i + 1,
            c.get('title') or '',
            c.get('scripture_ref') or '',
            c.get('date') or '',
            snippet,
            match_pct,
            c.get('source_file') or '',
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
# Open file handler
# ---------------------------------------------------------------------------

def open_file(result_num: int, chunks_state: list) -> str:
    """Open the Nth result file in the OS default application (Word / PowerPoint).

    Uses os.startfile() on Windows, subprocess on Linux/macOS.
    """
    if not chunks_state:
        return "No search results to open. Run a search first."

    idx = int(result_num) - 1
    if idx < 0 or idx >= len(chunks_state):
        return f"Result #{int(result_num)} does not exist (only {len(chunks_state)} results)."

    source = chunks_state[idx].get('source_file', '')
    if not source:
        return "No file path recorded for this result."

    path = Path(source).resolve()
    if not path.exists():
        return f"File not found on disk: {path}"

    try:
        if sys.platform == 'win32':
            os.startfile(str(path))
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', str(path)], check=True)
        else:
            import subprocess
            subprocess.run(['xdg-open', str(path)], check=True)
        return f"Opened: {path.name}"
    except Exception as e:
        return f"Could not open file: {e}"


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

def build_ui():
    import gradio as gr

    with gr.Blocks(title="AI-Powered Sermon Note Search") as demo:
        gr.Markdown("# AI-Powered Sermon Note Search")
        gr.Markdown("Search your sermon archive.")

        # Hidden state — holds the last set of retrieved chunks for the Open handler
        chunks_state = gr.State([])

        with gr.Row():
            query_box = gr.Textbox(
                label="Your question",
                lines=2,
                placeholder='e.g. "What did I preach about forgiveness?"',
                scale=4,
            )
            search_btn = gr.Button("Search", variant="primary", scale=1)

        answer_md = gr.Markdown(label="Answer", value="")

        results_df = gr.Dataframe(
            headers=["#", "Title", "Scripture", "Date", "Snippet", "Match %", "Source File"],
            datatype=["number", "str", "str", "str", "str", "str", "str"],
            label="Source Chunks",
            wrap=True,
        )

        # Open file row
        with gr.Row():
            result_num = gr.Number(
                value=1,
                minimum=1,
                maximum=5,
                step=1,
                label="Result #",
                scale=1,
            )
            open_btn = gr.Button("Open File", scale=2)
            open_status = gr.Textbox(
                label="",
                interactive=False,
                scale=4,
                show_label=False,
            )

        status_md = gr.Markdown(value="")

        # Search events
        search_outputs = [answer_md, results_df, status_md, chunks_state]
        search_btn.click(fn=handle_query, inputs=[query_box], outputs=search_outputs)
        query_box.submit(fn=handle_query, inputs=[query_box], outputs=search_outputs)

        # Open file event
        open_btn.click(fn=open_file, inputs=[result_num, chunks_state], outputs=[open_status])

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
