@echo off
rem setup.cmd - set up ContextMAX for this Windows user. No administrator rights needed.
rem Creates a private Python environment in %USERPROFILE%\ContextMAX\.venv, installs ContextMAX
rem and its readers there (your own Python is left alone), then checks what this PC can read.
rem Run it again at any time to update.
setlocal
set "HERE=%~dp0"
set "CMXHOME=%USERPROFILE%\ContextMAX"
set "VENV=%CMXHOME%\.venv"
if not exist "%CMXHOME%" mkdir "%CMXHOME%"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.11 or newer is needed: install it from python.org, then run this again.
  pause
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo Creating the private Python environment in %VENV% ...
  %PY% -m venv "%VENV%" || goto :fail
)
set "PIPARGS="
if exist "%HERE%wheels\requirements-lock.txt" (
  echo Installing from the bundled wheels, offline ...
  "%VENV%\Scripts\python.exe" -m pip install --no-index --find-links "%HERE%wheels" --require-hashes -r "%HERE%wheels\requirements-lock.txt" || goto :fail
  set "PIPARGS=--no-index --find-links %HERE%wheels --no-deps"
)
echo Installing ContextMAX ...
"%VENV%\Scripts\python.exe" -m pip install --upgrade %PIPARGS% "%HERE%." || goto :fail
echo.
"%VENV%\Scripts\python.exe" -m contextmax checkup
echo.
echo Done. Double-click ContextMAX.cmd to choose folders and build a project.
pause
exit /b 0

:fail
echo.
echo The installation did not finish. If pip reports a certificate error, your antivirus or
echo company proxy inspects HTTPS: set PIP_CERT to its certificate bundle and run this again.
pause
exit /b 1
