@echo off
echo Starting ShiftPress...

REM Check if virtual environment exists
if not exist ".venv" (
    echo Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Run the application
python main.py

REM If application crashed, pause to see error
if errorlevel 1 (
    echo.
    echo Application exited with an error. Check %%APPDATA%%\ShiftPress\shiftpress.log for details.
    pause
)
