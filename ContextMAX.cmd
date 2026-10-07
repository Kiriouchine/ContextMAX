@echo off
rem ContextMAX.cmd - open the ContextMAX window: choose folders, build, open the maps.
rem Uses the private environment that setup.cmd made; a developer checkout falls back to .venv.
setlocal
set "PYEXE=%USERPROFILE%\ContextMAX\.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYEXE%" (
  echo ContextMAX is not installed yet: double-click setup.cmd first.
  pause
  exit /b 1
)
"%PYEXE%" -m contextmax panel %*
