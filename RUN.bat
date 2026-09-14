@echo off
setlocal
cd /d "%~dp0"
if exist "dist\Zenless.exe" (
    start "" "dist\Zenless.exe" --native-ui
    exit /b 0
)
if not exist ".build-venv\Scripts\python.exe" (
    echo Run BUILD.bat first.
    pause
    exit /b 1
)
".build-venv\Scripts\python.exe" main.py --native-ui
if errorlevel 1 pause
