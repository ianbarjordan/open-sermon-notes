# sermon_notes.spec — PyInstaller spec for the Sermon Notes search app.
#
# Build:
#   .venv\Scripts\pyinstaller --noconfirm sermon_notes.spec
#
# Or via build\make_release.bat which wraps the above with venv activation,
# pre-flight checks, and a clean dist/build sweep.
#
# Notes:
#   * --onedir (the default for a spec without --onefile) — llama-cpp's
#     bundled DLL (llama.dll, BLAS variants) is large and doesn't behave
#     well inside the --onefile self-extracting archive.
#   * console=True so launch.bat's pastor-readable error pause works the
#     same way as in dev. The browser-based UI is unchanged.
#   * The LLM model file (Phi-3.5-mini ~2.4 GB) is NOT bundled here. It
#     is downloaded by setup.bat into %LOCALAPPDATA%/SermonNotes/models/
#     on first install, so the .exe distribution stays under ~600 MB
#     and an unattended re-install doesn't need to re-fetch it.

# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Heavy dependencies — collect_all = (datas, binaries, hiddenimports) for each.
# These libraries combine pure Python, native DLLs, and runtime data files;
# enumerating them by hand is brittle.
# ---------------------------------------------------------------------------

_datas = []
_binaries = []
_hiddenimports = []

for _pkg in ('faiss', 'llama_cpp', 'sentence_transformers', 'transformers',
             'tokenizers', 'huggingface_hub', 'gradio', 'gradio_client',
             'safetensors', 'sklearn', 'numpy', 'scipy'):
    try:
        d, b, h = collect_all(_pkg)
        _datas += d
        _binaries += b
        _hiddenimports += h
    except Exception as _e:
        print(f"[spec] WARNING: could not collect {_pkg!r}: {_e}")

# Build scripts are imported lazily from app/handlers.py (in-process bridge,
# Item 17 B-1). PyInstaller cannot trace lazy imports from a string, so
# enumerate them here.
_hiddenimports += [
    'build',
    'build.ingest_files',
    'build.chunk_embed',
    'build.chunk_text',
    'build.format_detect',
    'build.normalize_scripture',
    'build.parse_filename',
    'app',
    'app.app',
    'app.config',
    'app.handlers',
    'app.llm',
    'app.logging_config',
    'app.paths',
    'app.retriever',
]

# pywin32 — needed for Word COM parsing of .doc files on Windows.
# pywin32 ships .pyd extensions and registry-bound DLLs that PyInstaller's
# default hooks usually catch; the explicit names below are belt-and-braces.
_hiddenimports += [
    'win32com', 'win32com.client', 'win32api', 'win32con', 'pythoncom',
    'pywintypes',
]


a = Analysis(
    ['app/app.py'],
    pathex=['.'],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # IPython / Jupyter and friends are pulled in transitively by some
        # data-science deps but are 30+ MB of dead weight in our context.
        'IPython', 'jupyter', 'notebook', 'ipykernel',
        # PyTorch's CUDA libraries (we ship CPU-only). PyInstaller's collector
        # tends to grab them anyway; this excludes them by name.
        'torch.cuda', 'torch.distributed',
        # We do not ship the test suite.
        'pytest', '_pytest', 'pytest_asyncio',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SermonNotes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX can corrupt some native DLLs; skip
    console=True,               # keep stdout/stderr visible — see top of file
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                  # add an .ico path here once a brand asset exists
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SermonNotes',
)
