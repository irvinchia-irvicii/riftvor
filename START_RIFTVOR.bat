@echo off
setlocal
cd /d "%~dp0"
title Farsight Local Website

echo.
echo ========================================
echo   Farsight - Local Website
echo ========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo First-time setup: preparing Farsight...
    where py >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python is not installed or cannot be found.
        echo Install Python from https://www.python.org/downloads/windows/
        echo Select "Add python.exe to PATH" during installation.
        echo Then double-click this file again.
        echo.
        pause
        exit /b 1
    )

    py -m venv venv
    if errorlevel 1 goto :setup_failed

    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :setup_failed
)

echo Starting the website at http://127.0.0.1:5009
echo.
echo Keep this window open while using Farsight.
echo To stop the website, return here and press Ctrl+C.
echo.

start "" "http://127.0.0.1:5009"
"venv\Scripts\python.exe" app.py
exit /b %errorlevel%

:setup_failed
echo.
echo Farsight could not finish its first-time setup.
echo Leave this window open and ask Codex to inspect the error shown above.
echo.
pause
exit /b 1
