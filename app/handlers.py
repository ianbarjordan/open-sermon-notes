"""handlers.py — Shared helpers extracted from app/app.py.

This is the minimal extraction agreed as part of D-1 in the pre-delivery
code review: the retriever-reload block that previously appeared 4× in
app.py is collapsed to a single function here.

The broader app.py split (per-tab UI modules) is deferred to Item 18 (post-
delivery GUI polish); doing it pre-packaging would compound risk with the
PyInstaller refactor in Item 17. See plans/graceful-tickling-gray.md.
"""
from typing import Optional

from app.config import DB_PATH, FAISS_PATH, ID_MAP_PATH
from app.logging_config import get_logger

_log = get_logger(__name__)


def reload_retriever(sermon_root: str) -> tuple[Optional[object], str]:
    """Build a new Retriever for the given sermon_root.

    Returns (retriever_or_None, status_message). The caller is responsible
    for assigning the result to its module-level slot (we don't reach into
    other modules' globals from here).
    """
    try:
        from app.retriever import load_retriever as _load_retriever
        retriever = _load_retriever(
            db_path=DB_PATH, faiss_path=FAISS_PATH, idmap_path=ID_MAP_PATH,
            sermon_root=sermon_root,
        )
        return retriever, "Retriever reloaded successfully."
    except Exception as e:
        _log.error("Retriever reload failed", exc_info=True)
        return None, f"Retriever reload failed: {e}"
