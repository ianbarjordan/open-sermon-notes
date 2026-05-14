"""paths.py — Path resolution that survives PyInstaller freezing.

Three roles to keep distinct:

  project_root()  — Read-only bundled assets (Python source, default config,
                    bundled model README). Under PyInstaller --onedir this is
                    the directory containing the launcher .exe; in dev it is
                    the repository root.

  data_root()     — Writable user data (sermons.db, FAISS index, id_map,
                    settings.json, quarantine, logs). Under PyInstaller this
                    is %LOCALAPPDATA%/SermonNotes/ so the user's data
                    persists across reinstalls and never collides with
                    Program Files write protection. In dev it is the
                    repository root, so existing relative paths
                    ("data/sermons.db", "raw/quarantine", "logs/app.log")
                    continue to resolve as before.

  resolve_writable(relpath)
                  — Convenience: data_root() / relpath, with parent dirs
                    created.

The frozen check uses `getattr(sys, 'frozen', False)`, which PyInstaller
sets to True on the bundled launcher. No other code path sets this attr.
"""
import os
import sys
from pathlib import Path

_APP_FOLDER_NAME = "SermonNotes"


def is_frozen() -> bool:
    """True iff running inside a PyInstaller bundle."""
    return bool(getattr(sys, 'frozen', False))


def project_root() -> Path:
    """Read-only bundled-assets root.

    --onedir: the directory containing the launcher .exe (sys.executable lives
    there, and PyInstaller drops bundled data files alongside it).
    Dev mode: the repository root (two parents up from this file).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Writable user-data root.

    Frozen + Windows: %LOCALAPPDATA%/SermonNotes/
    Frozen + other:   ~/.sermonnotes/   (rarely hit — target is Windows)
    Dev mode:         the repository root (so existing relative paths still
                      resolve as they always did)
    """
    if not is_frozen():
        return Path(__file__).resolve().parent.parent

    appdata = os.environ.get('LOCALAPPDATA')
    if appdata:
        return Path(appdata) / _APP_FOLDER_NAME
    # Non-Windows fallback (rare for this app — target machine is Windows)
    return Path.home() / f".{_APP_FOLDER_NAME.lower()}"


def resolve_writable(relpath: str | Path) -> Path:
    """Return an absolute path under data_root(), creating parents as needed.

    Pass a project-relative path string like 'data/sermons.db' or
    'raw/quarantine'. In dev this resolves to the repo, in frozen mode it
    resolves under %LOCALAPPDATA%/SermonNotes/.
    """
    p = data_root() / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
