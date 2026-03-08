@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0.venv\Scripts\pythonw.exe" -m transcribator.gui
if errorlevel 1 (
    "%~dp0.venv\Scripts\python.exe" -m transcribator.gui
    pause
)
