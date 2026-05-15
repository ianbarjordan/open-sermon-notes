@echo off
setlocal

:: ---------------------------------------------------------------------------
:: make_release.bat — build the PyInstaller distribution of Sermon Notes.
::
:: Output: dist\SermonNotes\ (the --onedir bundle; ship the whole folder).
::
:: Run this from the project root, in a fresh cmd window. Run setup.bat
:: first if .venv is missing.
:: ---------------------------------------------------------------------------

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo ERROR: Virtual environment ^(.venv^) is missing.
    echo Run setup.bat first to install runtime dependencies.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Installing packaging dependencies...
pip install -q -r build\requirements_packaging.txt
if errorlevel 1 (
    echo.
    echo ERROR: Could not install pyinstaller. Check your internet connection
    echo or the version pin in build\requirements_packaging.txt.
    echo.
    pause
    exit /b 1
)

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
echo (Bundle size will be ~500 MB without the LLM model; ~3 GB with it.)
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

echo.
echo === Build complete ===
echo Output: dist\SermonNotes\
echo.
echo Next steps:
echo   1. Zip dist\SermonNotes\ for distribution
echo   2. The end user unzips, then runs SermonNotes.exe
echo   3. On first launch the app will look for the LLM model at
echo      %%LOCALAPPDATA%%\SermonNotes\models\Phi-3.5-mini-instruct-Q4_K_M.gguf
echo      If missing, the app prints clear instructions to download it.
echo.
pause
endlocal
