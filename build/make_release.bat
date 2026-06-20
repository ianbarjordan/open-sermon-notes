@echo off
setlocal

:: ---------------------------------------------------------------------------
:: make_release.bat — build the PyInstaller distribution of Sermon Notes.
::
:: Output: dist\SermonNotes\ (the --onedir bundle; ship the whole folder).
::
:: PREREQUISITE: build\setup_release_venv.bat must have been run once to
:: create .venv-build (a CPU-torch-only venv specifically for shipping).
:: See that script's header for why the dev .venv isn't used directly.
:: ---------------------------------------------------------------------------

if not exist ".venv-build\Scripts\activate.bat" (
    echo.
    echo ERROR: Release venv ^(.venv-build^) is missing.
    echo.
    echo The shipping bundle uses CPU-only torch, which lives in a separate
    echo venv so the dev .venv ^(which may have CUDA torch installed^) doesn't
    echo accidentally bloat the bundle by ~3.7 GB.
    echo.
    echo Fix: run build\setup_release_venv.bat ^(one-time setup^), then re-run
    echo this script.
    echo.
    pause
    exit /b 1
)

call .venv-build\Scripts\activate.bat

echo Verifying packaging dependencies are present...
python -c "import PyInstaller, pefile, backports.tarfile" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Packaging deps incomplete in .venv-build — re-installing...
    pip install -q -r build\requirements_packaging.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Could not install pyinstaller. Check your internet
        echo connection or the version pin in build\requirements_packaging.txt.
        echo.
        pause
        exit /b 1
    )
)

echo.
echo Sanity-check: confirming this venv has CPU torch ^(not CUDA^)...
for /f "tokens=*" %%v in ('python -c "import torch; print(torch.__version__)"') do set TORCH_VER=%%v
echo Torch version: %TORCH_VER%
echo %TORCH_VER% | findstr /i "cu1" >nul
if not errorlevel 1 (
    echo.
    echo WARNING: .venv-build appears to have CUDA torch installed ^(%TORCH_VER%^).
    echo The resulting bundle will be 4 GB+ and may fail to load CUDA DLLs on
    echo target machines without a GPU.
    echo.
    echo To fix: delete .venv-build and re-run build\setup_release_venv.bat.
    echo.
    pause
    exit /b 1
)
echo OK — CPU torch detected.

echo.
echo Running the test suite as a build pre-flight...
python -m pytest tests\ -q
if errorlevel 1 (
    echo.
    echo ERROR: Tests failed. Refusing to ship a build on a red suite.
    echo.
    pause
    exit /b 1
)

echo.
echo Cleaning previous build artifacts...
if exist dist\SermonNotes rmdir /s /q dist\SermonNotes
if exist build\SermonNotes rmdir /s /q build\SermonNotes

echo.
echo Running PyInstaller. This takes several minutes.
pyinstaller --noconfirm --clean sermon_notes.spec
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed. See the output above.
    echo Common causes:
    echo   * A native dependency moved its DLLs in a version bump
    echo   * Hidden-imports list in sermon_notes.spec is out of date
    echo.
    pause
    exit /b 1
)

echo.
echo Smoke test: launching the bundle in --help mode...
"dist\SermonNotes\SermonNotes.exe" --help >nul 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: SermonNotes.exe --help exited non-zero. The bundle may
    echo still run, but inspect the build output before shipping.
    echo.
)

:: ---------------------------------------------------------------------------
:: Inno Setup installer build.
::
:: Wraps the dist\SermonNotes\ bundle + the LLM model into a single
:: SermonNotes-Setup-<VERSION>.exe that the recipient double-clicks.
:: See SermonNotes.iss for the layout and install behavior.
::
:: Skipped (with a clear message) if Inno Setup isn't installed — the
:: PyInstaller bundle alone is still usable for a manual unzip-style ship.
:: ---------------------------------------------------------------------------
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"

if exist "%ISCC%" (
    echo.
    echo Building installer with Inno Setup. This takes ~3-5 minutes ^(LZMA2/max^)...
    "%ISCC%" SermonNotes.iss
    if errorlevel 1 (
        echo.
        echo WARNING: Inno Setup build failed. The PyInstaller bundle at
        echo dist\SermonNotes\ is still usable; you can ship that folder
        echo as a zip instead while the installer issue is sorted.
        echo.
    )
) else (
    echo.
    echo NOTE: Inno Setup 6 not found at the standard install paths.
    echo Skipping installer build. Install from https://jrsoftware.org/isdl.php
    echo to enable single-exe installer output.
    echo.
)

echo.
echo === Build complete ===
echo.
echo PyInstaller bundle: dist\SermonNotes\
if exist "dist\SermonNotes-Setup-1.0.0.exe" (
    echo Installer:          dist\SermonNotes-Setup-1.0.0.exe
    echo.
    echo Ship the installer ^(single .exe^) for the simplest end-user experience:
    echo   1. Recipient double-clicks SermonNotes-Setup-1.0.0.exe
    echo   2. Clicks through the wizard ^(no admin rights needed^)
    echo   3. App launches; they set their sermon folder; done.
) else (
    echo.
    echo Installer was not produced. Ship the dist\SermonNotes\ folder as a zip
    echo and follow the manual install steps in INSTALL.txt.
)
echo.
pause
endlocal
