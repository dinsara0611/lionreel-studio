@echo off
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
    start "" ".venv\Scripts\pythonw.exe" web_server.py
) else (
    start "" pythonw.exe web_server.py
)
