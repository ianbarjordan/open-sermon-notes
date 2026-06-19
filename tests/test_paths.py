"""Tests for app/paths.py — frozen-aware path resolution (Item 17 B-2)."""
import os
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import paths


# ---------------------------------------------------------------------------
# is_frozen
# ---------------------------------------------------------------------------

def test_is_frozen_default_false():
    """In a normal dev run, sys.frozen is not set → False."""
    # Force-remove the attribute if a previous test (or PyInstaller dev install)
    # left it set, so this assertion isn't environment-dependent.
    with mock.patch.object(sys, 'frozen', False, create=True):
        assert paths.is_frozen() is False


def test_is_frozen_true_when_pyinstaller_sets_attribute():
    with mock.patch.object(sys, 'frozen', True, create=True):
        assert paths.is_frozen() is True


# ---------------------------------------------------------------------------
# project_root
# ---------------------------------------------------------------------------

def test_project_root_in_dev_returns_repo_root():
    """Dev mode: project_root() is the repo root (parent of app/)."""
    with mock.patch.object(sys, 'frozen', False, create=True):
        root = paths.project_root()
    # Must contain at minimum app/, build/, tests/ — the project layout
    assert (root / "app").is_dir()
    assert (root / "build").is_dir()
    assert (root / "tests").is_dir()


def test_project_root_frozen_uses_executable_dir():
    """Frozen mode: project_root() is the directory containing sys.executable."""
    with mock.patch.object(sys, 'frozen', True, create=True), \
         mock.patch.object(sys, 'executable', r"C:\Program Files\SermonNotes\launcher.exe"):
        assert paths.project_root() == Path(r"C:\Program Files\SermonNotes")


# ---------------------------------------------------------------------------
# data_root
# ---------------------------------------------------------------------------

def test_data_root_in_dev_returns_repo_root():
    """Dev mode: data_root() returns the repo root so existing relative
    paths ('data/sermons.db', etc.) keep resolving exactly as before."""
    with mock.patch.object(sys, 'frozen', False, create=True):
        root = paths.data_root()
    assert (root / "app").is_dir()


def test_data_root_frozen_windows_uses_localappdata(tmp_path):
    """Frozen + Windows: %LOCALAPPDATA%/SermonNotes/"""
    fake_appdata = tmp_path / "AppData" / "Local"
    fake_appdata.mkdir(parents=True)
    with mock.patch.object(sys, 'frozen', True, create=True), \
         mock.patch.dict(os.environ, {'LOCALAPPDATA': str(fake_appdata)}, clear=False):
        root = paths.data_root()
    assert root == fake_appdata / "SermonNotes"


def test_data_root_frozen_without_localappdata_falls_back_to_home():
    """If LOCALAPPDATA is unset (unusual on Windows; common on Linux/macOS),
    fall back to ~/.sermonnotes/ so the user still gets a stable writable
    location."""
    env_without_appdata = {k: v for k, v in os.environ.items() if k != 'LOCALAPPDATA'}
    with mock.patch.object(sys, 'frozen', True, create=True), \
         mock.patch.dict(os.environ, env_without_appdata, clear=True):
        root = paths.data_root()
    assert root.name == ".sermonnotes"
    assert root.parent == Path.home()


# ---------------------------------------------------------------------------
# resolve_writable
# ---------------------------------------------------------------------------

def test_resolve_writable_joins_relative_path(tmp_path):
    """Relative input → data_root() / relative."""
    with mock.patch.object(paths, 'data_root', return_value=tmp_path):
        result = paths.resolve_writable("data/sermons.db")
    assert result == tmp_path / "data" / "sermons.db"


def test_resolve_writable_creates_parent_dirs(tmp_path):
    """The parent directory should exist after the call."""
    with mock.patch.object(paths, 'data_root', return_value=tmp_path):
        result = paths.resolve_writable("nested/deep/file.json")
    assert result.parent.is_dir()


def test_resolve_writable_absolute_input_passes_through(tmp_path):
    """An absolute path should NOT get re-rooted under data_root()."""
    abs_input = tmp_path / "explicit" / "override.db"
    with mock.patch.object(paths, 'data_root', return_value=Path(r"C:\should\not\be\used")):
        result = paths.resolve_writable(str(abs_input))
    assert result == abs_input
