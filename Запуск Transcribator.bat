@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe" set "PATH=%~dp0ffmpeg-8.0.1-essentials_build\bin;%PATH%"
"%~dp0.venv\Scripts\pythonw.exe" -m transcribator.gui
if errorlevel 1 (
    "%~dp0.venv\Scripts\python.exe" -m transcribator.gui
    pause
)
