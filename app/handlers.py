"""handlers.py — Shared helpers extracted from app/app.py.

What lives here:

  reload_retriever(sermon_root)         — minimal extraction from the
                                          pre-delivery review (D-1).
  run_ingest(...) / run_embed(...)      — in-process bridge to the build
                                          scripts (Item 17 B-1). Replaces the
                                          subprocess.run(sys.executable, ...)
                                          pattern that breaks under PyInstaller.

Both run_ingest and run_embed capture stdout/stderr into a StringIO so the
caller receives the same "raw log" string the subprocess pipeline used to
produce, and the technical-log accordion in the UI keeps working unchanged.
"""
import argparse
import contextlib
import io
import logging
import sys
import traceback
from typing import Optional

from app.config import DB_PATH, FAISS_PATH, ID_MAP_PATH
from app.logging_config import get_logger
from app.paths import resolve_writable

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
            db_path=str(resolve_writable(DB_PATH)),
            faiss_path=str(resolve_writable(FAISS_PATH)),
            idmap_path=str(resolve_writable(ID_MAP_PATH)),
            sermon_root=sermon_root,
        )
        return retriever, "Retriever reloaded successfully."
    except Exception as e:
        _log.error("Retriever reload failed", exc_info=True)
        return None, f"Retriever reload failed: {e}"


# ---------------------------------------------------------------------------
# In-process build-script bridge (Item 17 B-1)
# ---------------------------------------------------------------------------

class _LogHandler(logging.Handler):
    """Forward log records into the captured-stdout buffer.

    Build scripts use plain print(), but their dependencies (sentence-
    transformers, faiss, etc.) emit via the logging module. We attach this
    handler temporarily so those messages join the same buffer that the UI's
    technical-log accordion displays.
    """

    def __init__(self, buf: io.StringIO):
        super().__init__()
        self._buf = buf

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buf.write(self.format(record) + "\n")
        except Exception:
            pass


def _capture_run(callable_fn, label: str) -> str:
    """Execute callable_fn() with stdout/stderr/logging captured.

    Returns the captured text. Mimics the output shape of the previous
    `_run_subprocess` helper:
      - successful runs return the captured output
      - non-zero return values get "[exit code: N]" appended
      - unhandled exceptions append "[stderr]" + traceback + exit-code line
    """
    buf = io.StringIO()
    root_logger = logging.getLogger()
    handler = _LogHandler(buf)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root_logger.addHandler(handler)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                rc = callable_fn()
            except Exception as e:
                # Match the subprocess style: full traceback into [stderr]
                buf.write("\n[stderr]\n")
                buf.write(traceback.format_exc())
                buf.write(f"\n[exit code: 1]")
                _log.error("%s raised an exception", label, exc_info=True)
                return buf.getvalue()
        if isinstance(rc, int) and rc != 0:
            buf.write(f"\n[exit code: {rc}]")
            _log.error("%s exited with code %d", label, rc)
    finally:
        root_logger.removeHandler(handler)
    return buf.getvalue()


def run_ingest(
    *,
    source: str,
    force: bool = False,
    verbose: bool = True,
    limit: int = 0,
    dry_run: bool = False,
) -> str:
    """Run the ingest pipeline in-process and return its captured output.

    Replaces `subprocess.run([sys.executable, "build/ingest_files.py", ...])`.
    Works in a PyInstaller bundle because no external python interpreter is
    required. All output paths resolve via data_root() so writes land in
    %LOCALAPPDATA%/SermonNotes/ under frozen and in the repo in dev.
    """
    from build import ingest_files as _ingest

    args = argparse.Namespace(
        source=source,
        out=str(resolve_writable('data/documents')),
        quarantine=str(resolve_writable('raw/quarantine')),
        limit=limit,
        dry_run=dry_run,
        force=force,
        verbose=verbose,
        registry=str(resolve_writable(_ingest.PROCESSED_REGISTRY)),
        no_progress=True,  # captured stdout — no carriage-returned progress bar
    )
    return _capture_run(lambda: _ingest.run(args), "build.ingest_files.run")


def run_embed(
    *,
    incremental: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> str:
    """Run the chunk+embed pipeline in-process. Returns captured output."""
    from build import chunk_embed as _embed
    from app.config import DOCUMENTS_DIR, EMBED_MODEL

    args = argparse.Namespace(
        docs=str(resolve_writable(DOCUMENTS_DIR)),
        db=str(resolve_writable(DB_PATH)),
        faiss=str(resolve_writable(FAISS_PATH)),
        idmap=str(resolve_writable(ID_MAP_PATH)),
        model=EMBED_MODEL,
        batch=64,
        force=force,
        dry_run=dry_run,
        incremental=incremental,
        no_progress=True,
    )
    return _capture_run(lambda: _embed.run(args), "build.chunk_embed.run")
