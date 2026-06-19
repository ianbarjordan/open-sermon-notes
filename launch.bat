@echo off
setlocal

:: Sermon-notes launcher. Designed to fail loudly when something is wrong
:: so the pastor sees a clear next step instead of a window that flashes
:: and closes.

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo ERROR: Virtual environment ^(.venv^) is missing.
    echo.
    echo This usually means setup hasn't been run yet, or the project
    echo folder was moved or copied without the .venv inside it.
    echo.
    echo Fix: double-click setup.bat to install everything, then try
    echo launch.bat again.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo Starting sermon search app...
echo The browser will open automatically once the app has finished loading.
echo This can take 30 seconds on a cold start.
echo.

python app\app.py --port 7860

:: If app.py exits with an error, hold the console open so the pastor can
:: read the message before the window closes.
if errorlevel 1 (
    echo.
    echo The app exited with an error. The message above ^(and logs\app.log^)
    echo should explain what went wrong. Re-run setup.bat if the problem
    echo persists.
    echo.
    pause
)

endlocal
