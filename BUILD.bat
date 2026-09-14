@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 goto missing_python
where npm >nul 2>nul
if errorlevel 1 goto missing_node
if not exist ".build-venv\Scripts\python.exe" python -m venv .build-venv
if errorlevel 1 goto failed
call ".build-venv\Scripts\activate.bat"
python -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
powershell -NoProfile -File "%~dp0build.ps1" -FrontendIntegration -SkipInstaller
if errorlevel 1 goto failed
echo Build complete: dist\Zenless.exe
pause
exit /b 0
:missing_python
echo Python 3.14 is required to build from source.
goto failed
:missing_node
echo Node.js and npm are required to compile the detail workspaces.
:failed
echo Build failed. Review the error above.
pause
exit /b 1
