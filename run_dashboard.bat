@echo off
title LionReel Studio Dashboard
cd /d "%~dp0"
if "%LIONREEL_ROOT%"=="" set "PYTHONPYCACHEPREFIX=C:\LionReel\pycache"
echo ============================================================
echo   Starting LionReel Studio Dashboard...
echo ============================================================
if exist .venv\Scripts\python.exe (
    ".venv\Scripts\python.exe" web_server.py
) else (
    python web_server.py
)
if errorlevel 1 (
    echo.
    echo [ERROR] Server exited with code %errorlevel%.
    pause
)
