@echo off
setlocal

:: ---------------------------------------------------------------------------
:: setup_release_venv.bat — create the dedicated build venv used by
:: make_release.bat to produce shipping bundles.
::
:: WHY A SEPARATE VENV?
::   PyInstaller's torch hook collects every DLL in `torch\lib\`. The cu128
::   torch wheel that lives in the dev .venv hard-links `torch.dll`,
::   `torch_python.dll`, and `shm.dll` against `torch_cuda.dll` — meaning
::   you cannot strip the (774 MB) `torch_cuda.dll` from the bundle without
::   torch failing to import entirely. The CPU-only torch wheel doesn't
::   have those CUDA links, so stripping is moot and the bundle is small
::   AND it boots.
::
::   Keeping a separate `.venv-build` keeps the dev .venv (often CUDA-built
::   for unrelated work) intact while ensuring releases are reproducible
::   regardless of the dev's local torch flavor.
::
:: WHAT THIS SCRIPT DOES
::   1. Verify uv is available (setup.bat installs it for the dev venv).
::   2. Create .venv-build with Python 3.11.
::   3. Install CPU-only torch from the official CPU wheel index.
::   4. Install build and app runtime requirements (uses .venv-build's pip).
::   5. Install the packaging-only requirements (pyinstaller).
::
:: Run this ONCE; then `build\make_release.bat` reuses .venv-build for every
:: release. Re-run only when bumping pinned versions or rebuilding from
:: scratch.
:: ---------------------------------------------------------------------------

where uv >nul 2>&1 || (
    echo.
    echo ERROR: 'uv' is not on PATH. Run setup.bat first ^(it installs uv^).
    echo.
    pause & exit /b 1
)

if exist .venv-build (
    echo .venv-build already exists.
    echo Delete it manually if you want to rebuild from scratch ^(rmdir /s /q .venv-build^),
    echo or re-run this script after deletion.
    echo.
    pause & exit /b 0
)

echo Creating .venv-build with Python 3.11...
uv venv .venv-build --python 3.11
if errorlevel 1 (
    echo.
    echo ERROR: Could not create the build venv.
    echo Install Python 3.11 from https://python.org/downloads if missing.
    echo.
    pause & exit /b 1
)

:: Use the venv's python.exe directly instead of `activate.bat`.
:: When this script runs under `cmd /c "build\setup_release_venv.bat"`, the
:: `call activate.bat` mutation does NOT always persist to subsequent
:: commands in the nested cmd context — pip ends up running against the
:: system Python and the venv stays empty. Direct python -m pip avoids the
:: ambiguity entirely.
set "VENV_PY=.venv-build\Scripts\python.exe"
%VENV_PY% -m ensurepip --upgrade >nul 2>&1

echo.
echo Installing CPU-only PyTorch (this is the key difference from .venv)...
%VENV_PY% -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo.
    echo ERROR: torch CPU install failed. Check your internet connection.
    echo.
    pause & exit /b 1
)

echo.
echo Installing build dependencies...
%VENV_PY% -m pip install -r build\requirements_build.txt

echo.
echo Installing app dependencies...
%VENV_PY% -m pip install -r app\requirements_app.txt

echo.
echo Installing packaging-only dependencies ^(pyinstaller^)...
%VENV_PY% -m pip install -r build\requirements_packaging.txt

echo.
echo Verifying torch flavor...
%VENV_PY% -c "import torch; v=torch.__version__; assert '+cu' not in v and 'cu1' not in v, 'Expected CPU torch but got '+v; print('OK: torch '+v)"
if errorlevel 1 (
    echo.
    echo ERROR: The installed torch is the CUDA wheel, not the CPU wheel.
    echo Delete .venv-build and re-run this script; pip may have grabbed a
    echo cached wheel from a previous CUDA install.
    echo.
    pause & exit /b 1
)

echo.
echo === Release venv ready ===
echo Run build\make_release.bat to produce the shipping bundle.
echo.
pause
endlocal
