@echo off
rem Migration Forge CLI launcher for Windows cmd and PowerShell. Usage: forge ^<command^> [args...]; forge help
setlocal
set "FORGE_PY=%~dp0..\scripts\forge.py"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 && goto :py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 && goto :python
echo migration-forge: Python ^>= 3.9 not found (tried py -3, python) 1>&2
exit /b 1
:py
py -3 "%FORGE_PY%" %*
exit /b %errorlevel%
:python
python "%FORGE_PY%" %*
exit /b %errorlevel%
