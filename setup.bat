@echo off
echo === sermon-notes-offline Setup ===
echo.

:: ---------------------------------------------------------------------------
:: Find a Python 3.11 executable.
:: Try in order: py launcher (preferred), then bare python command.
:: uv will do its own resolution when creating the venv, so this block is
:: only used to install uv itself if it is missing.
:: ---------------------------------------------------------------------------
set PY=
where py >nul 2>&1 && (
    py -3.11 --version >nul 2>&1 && set PY=py -3.11
)
if "%PY%"=="" (
    python --version 2>nul | findstr "3.11" >nul && set PY=python
)
if "%PY%"=="" (
    echo NOTE: Python 3.11 not found on PATH.
    echo uv will attempt to locate or download it automatically.
    echo If setup fails, install Python 3.11 from https://python.org/downloads
    echo.
    set PY=python
)

:: Install uv if missing
where uv >nul 2>&1 || (
    echo Installing uv...
    %PY% -m pip install uv
)

:: Create venv — uv resolves Python 3.11 from any installed location
echo Creating virtual environment (Python 3.11)...
uv venv .venv --python 3.11
if errorlevel 1 (
    echo.
    echo ERROR: Could not create a Python 3.11 venv.
    echo Install Python 3.11 from https://python.org/downloads
    echo Make sure to check "Add Python to PATH" during installation.
    pause & exit /b 1
)
call .venv\Scripts\activate.bat

:: Install PyTorch (CPU build — smaller download, works on all machines)
echo Installing PyTorch (CPU)...
pip install torch --index-url https://download.pytorch.org/whl/cpu

:: Install project dependencies
echo Installing build dependencies...
pip install -r build\requirements_build.txt
echo Installing app dependencies...
pip install -r app\requirements_app.txt

:: Verify pywin32 (required for .doc parsing via Word COM)
python -c "import win32com.client; print('pywin32 OK')" 2>nul || (
    echo Attempting pywin32 post-install...
    python .venv\Lib\site-packages\pywin32_postinstall.py -install 2>nul
)

:: Download LLM model (~2.4 GB, one-time)
echo.
echo Downloading LLM model (~2.4 GB, one-time)...
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='bartowski/Phi-3.5-mini-instruct-GGUF', filename='Phi-3.5-mini-instruct-Q4_K_M.gguf', local_dir='models')"

echo.
echo === Setup complete! ===
echo Run launch.bat to start the app.
echo.
pause
