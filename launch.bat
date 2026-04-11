@echo off
call .venv\Scripts\activate.bat
echo Starting sermon search app...
start "" http://127.0.0.1:7860
python app\app.py --port 7860
