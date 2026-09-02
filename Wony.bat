@echo off
setlocal
REM Starts Wony in the background: tray icon plus the web page.
REM Uses the project venv when setup.py made one, otherwise plain python.

cd /d "%~dp0"

if not exist ".wony_setup" (
    echo.
    echo   Wony is not set up yet. Double-click install.bat first.
    echo.
    pause
    exit /b 1
)

if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" wony.py tray
    exit /b 0
)

where pythonw >nul 2>nul
if errorlevel 1 (
    python wony.py tray
) else (
    start "" pythonw wony.py tray
)
