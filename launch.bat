@echo off
call .venv\Scripts\activate.bat
echo Starting sermon search app...
echo The browser will open automatically once the app has finished loading.
python app\app.py --port 7860
