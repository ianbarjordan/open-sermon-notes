@echo off
echo === sermon-notes-offline Setup ===
echo.

:: Check Python 3.11
python --version 2>nul | findstr "3.11" >nul || (
    echo ERROR: Python 3.11 required.
    echo Download from https://python.org/downloads
    pause & exit /b 1
)

:: Install uv if missing
where uv >nul 2>&1 || (
    echo Installing uv...
    pip install uv
)

:: Create venv
echo Creating virtual environment...
uv venv .venv --python 3.11
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
