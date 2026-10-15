@echo off
rem make-offline-installer.cmd - on a PC with internet, make the installer for a PC without internet.
rem The result is dist\ContextMAX-<version>-offline.zip in this folder. Copy it to the other PC, unzip
rem it there and double-click setup.cmd: nothing has to be installed on that PC first.
rem It runs this folder's ContextMAX code with a Python this PC has: the one of an installed ContextMAX,
rem or a Python 3.11 or newer. Only when there is none does it install ContextMAX here first (setup.cmd).
setlocal EnableExtensions DisableDelayedExpansion
set "CMXHOME=%USERPROFILE%\ContextMAX"
if defined CONTEXTMAX_HOME set "CMXHOME=%CONTEXTMAX_HOME%"
set "PYEXE=%CMXHOME%\.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :make
set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :make
set "PYEXE="
where py >nul 2>nul && for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2^>nul') do set "PYEXE=%%p"
if defined PYEXE goto :make
where python >nul 2>nul && for /f "delims=" %%p in ('python -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2^>nul') do set "PYEXE=%%p"
if defined PYEXE goto :make
echo This PC has no Python 3.11 or newer, so ContextMAX is installed here first (it brings its own
echo Python); then the offline installer is made.
echo.
call "%~dp0setup.cmd" /quiet
if errorlevel 1 goto :failed
set "PYEXE=%CMXHOME%\.venv\Scripts\python.exe"
:make
set "PYTHONPATH=%~dp0src"
"%PYEXE%" -m contextmax offline-installer --source "%~dp0." --out "%~dp0dist" || goto :failed
echo.
if /i not "%~1"=="/quiet" pause
exit /b 0
:failed
echo.
echo The offline installer was not made; the messages above say why.
if /i not "%~1"=="/quiet" pause
exit /b 1
