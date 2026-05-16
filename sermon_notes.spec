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
             # safehttpx, groovy, pydantic, etc. are gradio dependencies that
             # read packaged data files at import time (version.txt, schema
             # files, templates). Let collect_all enumerate them so we don't
             # have to chase each one manually.
             'safehttpx', 'groovy',
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

# setuptools >= 60 vendors jaraco.context which transitively imports
# backports.tarfile from PyInstaller's pyi_rth_pkgres runtime hook. Without
# these, the bundle crashes at startup before any app code runs.
_hiddenimports += ['backports', 'backports.tarfile']


a = Analysis(
    ['app/app.py'],
    pathex=['.'],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        # Numpy 2.x and delvewheel-built wheels ship their native deps in
        # sibling `.libs/` directories. PyInstaller's frozen-import path
        # sometimes skips the wheel's _distributor_init side-effect, which
        # leaves Windows unable to find the openblas DLL when
        # _multiarray_umath.pyd loads. This hook adds every *.libs dir in
        # the bundle root to the DLL search path before any imports.
        'pyi_rth_libs.py',
    ],
    excludes=[
        # IPython / Jupyter and friends are pulled in transitively by some
        # data-science deps but are 30+ MB of dead weight in our context.
        'IPython', 'jupyter', 'notebook', 'ipykernel',
        # PyTorch's CUDA submodules (we ship CPU-only). PyInstaller's
        # collector tends to grab them anyway; this excludes them by name.
        # The matching .dll filtering happens just below for the binaries
        # that the `excludes=` list above doesn't reach.
        'torch.cuda', 'torch.distributed',
        # We do not ship the test suite.
        'pytest', '_pytest', 'pytest_asyncio',
    ],
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------------------
# Strip CUDA / cuDNN / cuBLAS DLLs.
#
# The dev venv has torch==2.11.0+cu128 installed for tooling reasons, but the
# target machine is CPU-only and PLAN.md item 17 explicitly bans shipping the
# CUDA stack. PyInstaller's hooks for torch pull every DLL in `torch\lib\`
# regardless of `excludes=['torch.cuda']` above (that only filters the Python
# module graph, not the binary list).
#
# This drops the bundle from ~4.6 GB to ~900 MB. If a future CUDA build is
# wanted, replace this filter with a `--no-cuda-strip` flag or a separate
# spec.
# ---------------------------------------------------------------------------
# What to strip:
#   The cu128 torch wheel in the dev venv pulls every CUDA / cuDNN / NVIDIA-
#   tooling DLL into the bundle (~3.7 GB). The target machine is CPU-only,
#   so all of it is dead weight — but stripping inconsistently is worse than
#   not stripping at all: torch._load_dll_libraries iterates torch\lib\*.dll
#   and crashes if a sibling like c10_cuda.dll references a stripped lib.
#
# What to KEEP (special case):
#   cudart64_*.dll is a small (~1 MB) ABI stub. torch_cpu.dll has a
#   load-time link against cudart even on CPU codepaths. Removing it
#   breaks the entire torch import chain → numpy via sentence_transformers
#   → ImportError DLL load failed.
#
# Net result with the patterns below: 4.6 GB → ~700 MB.
# Verified via `pefile` against the CUDA torch wheel:
#   torch_cpu.dll imports  → cudart64_12.dll, cupti64_2025.1.1.dll, c10.dll
#   shm.dll       imports  → torch_cuda.dll  (hard static import!)
# So:
#   * KEEP cudart and cupti — load-time deps of torch_cpu
#   * STRIP shm — it has a hard import on the stripped torch_cuda; if shm is
#     left in the bundle, torch._load_dll_libraries blows up trying to load
#     it. Our app never touches torch's multiprocess shared memory (no
#     DataLoader workers), so it's safe to drop.
_CUDA_BINARY_PATTERNS = (
    'cuda',          # c10_cuda.dll and friends. Special-cased below to
                     # keep cudart specifically.
    'cudnn',         # cuDNN deep-learning ops
    'cublas',        # GPU BLAS (covers cublas, cublasLt)
    'cufft',         # GPU FFT
    'curand',        # GPU RNG
    'cusolver',      # solver (covers cusolverMg)
    'cusparse',      # GPU sparse
    'nvrtc',         # NVIDIA RTC
    'nvjit',         # JIT (covers nvJitLink)
    'nvjpeg',        # GPU JPEG
    'nccl',          # multi-GPU collectives — never needed
    'nvperf',        # NVIDIA performance tools
    'nvtools',       # NVIDIA Tools Extension (nvToolsExt)
    'torch_cuda',    # the CUDA half of torch itself (774 MB)
    'shm',           # PyTorch shared-memory module — hard CUDA dep, unused
                     # by our app (no torch DataLoader workers).
)


def _is_cuda_binary(name: str) -> bool:
    lower = name.lower()
    # torch_cpu.dll has load-time imports of these — preserving them is
    # mandatory or torch fails to load and the whole import chain breaks.
    if 'cudart' in lower or 'cupti' in lower:
        return False
    return any(pat in lower for pat in _CUDA_BINARY_PATTERNS)


_before = len(a.binaries)
_stripped = [n for (n, p, t) in a.binaries if _is_cuda_binary(n)]
import os as _os
_STRIP_DISABLED = _os.environ.get('SERMON_NO_CUDA_STRIP') == '1'
if _STRIP_DISABLED:
    print(f"[spec] CUDA binary strip: DISABLED via SERMON_NO_CUDA_STRIP=1 "
          f"(would have stripped {len(_stripped)} of {_before})")
else:
    a.binaries = [(n, p, t) for (n, p, t) in a.binaries if not _is_cuda_binary(n)]
    a.datas    = [(n, p, t) for (n, p, t) in a.datas    if not _is_cuda_binary(n)]
    print(f"[spec] CUDA binary strip: {_before} -> {len(a.binaries)} entries")
    for _n in sorted(_stripped):
        print(f"[spec]   stripped: {_n}")

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
