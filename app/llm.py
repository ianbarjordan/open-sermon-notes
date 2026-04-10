"""
llm.py — Wrap llama_cpp.Llama for Phi-3.5-mini-instruct. Expose generate().

Usage:
    python app/llm.py --query "What sermons did I preach on grace?" --chunks path/to/chunks.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import (  # noqa: E402
    CTX_WINDOW,
    MODEL_PATH,
    N_GPU_LAYERS,
    N_THREADS,
    USE_MMAP,
)

_SYSTEM_PROMPT = """\
You are a pastoral research assistant. Your job is to help a pastor find
relevant content from their own sermon archive spanning over 27 years.

Answer ONLY from the sermon excerpts provided below. Do NOT use outside
knowledge. If the excerpts do not contain enough information to answer
the question, say so plainly — do not fabricate content.

When referencing a sermon, cite it by title and scripture reference if
available. Keep your answer concise (3-5 sentences) unless the pastor
asks for more detail.\
"""


def _format_chunk(i: int, chunk: dict) -> str:
    """Format a single chunk for the context block in the user message."""
    title = chunk.get('title') or '(untitled)'
    scripture = chunk.get('scripture_ref')
    date = chunk.get('date')
    source = chunk.get('source_file') or ''
    text = chunk.get('text') or ''

    header = f'[{i}] "{title}"'
    if scripture:
        header += f' ({scripture})'
    if date:
        header += f' — {date}'
    return f"{header}\nSource: {source}\n---\n{text}"


def _build_user_message(query: str, chunks: list[dict]) -> str:
    excerpts = '\n\n'.join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))
    return f"Sermon excerpts:\n\n{excerpts}\n\n---\nQuestion: {query}"


# ---------------------------------------------------------------------------
# LLM wrapper
# ---------------------------------------------------------------------------

class LLM:
    def __init__(self, llama):
        self._llama = llama

    def generate(
        self,
        query: str,
        chunks: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.1,
        stream: bool = False,
    ) -> str:
        """Generate an answer from the given query and chunk context.

        stream=False only in v1.
        """
        user_message = _build_user_message(query, chunks)
        messages = [
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user',   'content': user_message},
        ]
        response = self._llama.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        return response['choices'][0]['message']['content'].strip()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def load_llm(model_path: str = MODEL_PATH) -> LLM:
    """Load the GGUF model. Raises FileNotFoundError with instructions if missing."""
    if not Path(model_path).is_file():
        raise FileNotFoundError(
            f"Model not found: {model_path}\n\n"
            "Download it with:\n"
            "  .venv/bin/python -c \"\n"
            "  from huggingface_hub import hf_hub_download\n"
            "  hf_hub_download(\n"
            "      repo_id='bartowski/Phi-3.5-mini-instruct-GGUF',\n"
            "      filename='Phi-3.5-mini-instruct-Q4_K_M.gguf',\n"
            "      local_dir='models/')\n"
            "  \"\n"
        )

    try:
        from llama_cpp import Llama
    except ImportError:
        raise ImportError(
            "llama-cpp-python is not installed.\n"
            "Install with: .venv/bin/pip install llama-cpp-python"
        )

    llama = Llama(
        model_path=model_path,
        n_ctx=CTX_WINDOW,
        n_threads=N_THREADS,
        n_gpu_layers=N_GPU_LAYERS,
        use_mmap=USE_MMAP,
        verbose=False,
    )
    return LLM(llama)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='LLM wrapper for Phi-3.5-mini-instruct.')
    p.add_argument('--query',       metavar='TEXT', required=True, help='Search query')
    p.add_argument('--chunks',      metavar='PATH', default=None,
                   help='JSON file containing a list of chunk dicts (optional)')
    p.add_argument('--model',       metavar='PATH', default=MODEL_PATH)
    p.add_argument('--max-tokens',  metavar='INT',  type=int, default=512)
    p.add_argument('--temperature', metavar='FLOAT', type=float, default=0.1)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    chunks: list[dict] = []
    if args.chunks:
        with open(args.chunks, encoding='utf-8') as fh:
            chunks = json.load(fh)

    llm = load_llm(args.model)
    answer = llm.generate(args.query, chunks, args.max_tokens, args.temperature)
    print(answer)


if __name__ == '__main__':
    main()
