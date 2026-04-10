"""
app.py — Gradio 5 Blocks UI for offline sermon RAG search.

Usage:
    python app/app.py --port 7860
    python app/app.py --host 0.0.0.0 --port 7860 --share
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import DB_PATH, FAISS_PATH, ID_MAP_PATH, MODEL_PATH  # noqa: E402

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
    """Main event handler called by Gradio on submit.

    Returns (answer_str, dataframe_rows, status_str).
    """
    if not query or not query.strip():
        return "Please enter a question.", [], "No query."

    if _retriever is None:
        return (
            "Retriever is not available. Check startup logs.",
            [],
            "Error: retriever not loaded",
        )

    try:
        chunks = _retriever.search(query)
    except Exception as e:
        return f"Retrieval error: {e}", [], f"Error: {e}"

    if not chunks:
        return (
            "No relevant sermons found for this query.",
            [],
            "0 results",
        )

    # Build answer via LLM (or fallback if LLM not loaded)
    if _llm is not None:
        try:
            answer = _llm.generate(query, chunks)
        except Exception as e:
            answer = f"(LLM error: {e})\n\nTop result: {chunks[0].get('text', '')[:300]}"
    else:
        # Graceful degradation: show top chunk snippet without LLM
        top = chunks[0]
        answer = (
            f"**Note:** LLM not loaded — showing top match only.\n\n"
            f"**{top.get('title', '(untitled)')}** "
            f"({top.get('scripture_ref', '')})\n\n"
            f"{top.get('text', '')[:500]}..."
        )

    # Build dataframe rows
    rows = []
    for i, c in enumerate(chunks):
        snippet = (c.get('text') or '')[:120] + '...'
        rows.append([
            i + 1,
            c.get('title') or '',
            c.get('scripture_ref') or '',
            c.get('date') or '',
            snippet,
            c.get('source_file') or '',
        ])

    status = f"{len(chunks)} result(s) returned"
    return answer, rows, status


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

def build_ui():
    import gradio as gr

    with gr.Blocks(title="Sermon Notes — Offline RAG Search") as demo:
        gr.Markdown("# Sermon Notes — Offline RAG Search")
        gr.Markdown(
            "Search your 27-year sermon archive. "
            "Ask a question and get an AI-assisted answer with sources."
        )

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
            headers=["#", "Title", "Scripture", "Date", "Snippet", "Source File"],
            datatype=["number", "str", "str", "str", "str", "str"],
            label="Source Chunks",
            wrap=True,
        )

        status_md = gr.Markdown(value="")

        # Wire up events
        submit_inputs = [query_box]
        submit_outputs = [answer_md, results_df, status_md]

        search_btn.click(fn=handle_query, inputs=submit_inputs, outputs=submit_outputs)
        query_box.submit(fn=handle_query, inputs=submit_inputs, outputs=submit_outputs)

    return demo


# ---------------------------------------------------------------------------
# CLI + entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Gradio UI for offline sermon RAG search.')
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
