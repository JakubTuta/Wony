@echo off
setlocal enabledelayedexpansion
REM One-click installer for Wony. Double-click this file.
REM Everything it does is also available as: python setup.py

cd /d "%~dp0"
title Wony installer

echo.
echo   Wony installer
echo   --------------------------------------------------
echo.

REM A fresh Windows install can have "python.exe"/"py.exe" on PATH as a
REM Microsoft Store alias stub that only opens the Store when run — `where`
REM finds it, but it never prints a version, so that is the real check.
set "PY="
for %%C in (py.exe python.exe) do (
    if not defined PY (
        where %%C >nul 2>nul
        if not errorlevel 1 (
            set "PYVER="
            for /f "delims=" %%V in ('%%C --version 2^>^&1') do if not defined PYVER set "PYVER=%%V"
            echo !PYVER! | findstr /b "Python" >nul
            if not errorlevel 1 set "PY=%%~nC"
        )
    )
)

if not defined PY (
    echo   Python is not installed on this computer ^(or is only the Microsoft
    echo   Store's placeholder, which does not actually run it^).
    echo   Wony needs Python 3.10 or newer.
    echo.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo   Install it from https://www.python.org/downloads/
        echo   Tick "Add python.exe to PATH" in the installer, then run this file again.
        echo.
        pause
        exit /b 1
    )
    choice /c YN /m "  Install Python now"
    if errorlevel 2 (
        echo   Nothing installed. Get Python from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo.
    echo   Python installed. Close this window, open a new one, and run install.bat again
    echo   so Windows picks up the new program.
    echo.
    pause
    exit /b 0
)

echo   Using %PY%
echo.
echo   Starting setup. It asks which features you want, then for the keys
echo   and sign-ins those features need.
echo.
%PY% setup.py
set "RESULT=%ERRORLEVEL%"

echo.
if not "%RESULT%"=="0" (
    echo   Setup did not finish. Read the messages above, then run this file again.
) else (
    echo   Done. Start Wony by double-clicking Wony.bat
)
echo.
pause
