@echo off
rem setup.cmd - install ContextMAX for this Windows user. Double-click it; nothing else to install first.
rem
rem   1. Python: a private copy of the official Python, from nuget.org and checked against the SHA-256
rem      below, in %USERPROFILE%\ContextMAX\python. Your own Python, if you have one, is left alone.
rem      If that download is not possible (a company proxy may block it), a Python 3.11 or newer that is
rem      already on this PC is used; the packages still need the internet, or the offline installer.
rem   2. A private environment in %USERPROFILE%\ContextMAX\.venv with ContextMAX and its readers,
rem      RapidOCR text recognition for scans among them.
rem   3. A ContextMAX shortcut in the Start menu and on the desktop, the contextmax command, an
rem      entry in Apps ^& features and uninstall.cmd; RapidOCR's Cyrillic model (checked by SHA-256);
rem      then the check of what this PC can read.
rem
rem With a wheels folder next to it (the offline installer, made by make-offline-installer.cmd), it
rem installs from that folder alone, every file checked against its SHA-256.
rem No administrator rights. Run it again at any time to update. "setup.cmd /quiet" asks nothing
rem and opens nothing afterwards.
setlocal EnableExtensions DisableDelayedExpansion
set "HERE=%~dp0"
set "CMXHOME=%USERPROFILE%\ContextMAX"
if defined CONTEXTMAX_HOME set "CMXHOME=%CONTEXTMAX_HOME%"
rem the full name, in the case it has on disk and without a trailing backslash
for %%a in ("%CMXHOME%\.") do set "CMXHOME=%%~fa"
if defined CONTEXTMAX_HOME set "CONTEXTMAX_HOME=%CMXHOME%"
for %%a in ("%HERE%.") do set "SOURCE=%%~fa"
set "RUNTIME=%CMXHOME%\python"
set "VENV=%CMXHOME%\.venv"
rem what an update moves aside (a ContextMAX that is still open keeps running from it); removed at the end
set "OLDRUNTIME=%CMXHOME%\.python-old"
set "OLDVENV=%CMXHOME%\.venv-old"
set "PYVER=3.14.8"
set "PYSHA256=CE85F674D9A63029F709CBFF7A3DA1C6BC5BFCFAEFDD9999F98FA0290470C454"
set "PYURL=https://api.nuget.org/v3-flatcontainer/python/%PYVER%/python.%PYVER%.nupkg"
rem A company mirror can serve the same file: set CONTEXTMAX_PYTHON_URL to its address (the checksum still applies).
if defined CONTEXTMAX_PYTHON_URL set "PYURL=%CONTEXTMAX_PYTHON_URL%"
set "QUIET="
set "RENEWED="
set "BUSY="
if /i "%~1"=="/quiet" set "QUIET=1"
if /i "%SOURCE%"=="%CMXHOME%" goto :same_folder
if not exist "%CMXHOME%" mkdir "%CMXHOME%" || goto :fail

echo Installing ContextMAX in "%CMXHOME%"
echo.
call :private_python
if defined BUSY goto :stop
if errorlevel 1 call :system_python
if errorlevel 1 goto :no_python
call :environment || goto :fail
call :packages || goto :fail
"%VENV%\Scripts\python.exe" -m contextmax install %CONTEXTMAX_SETUP_ARGS% || goto :fail
call :ocr_models
if exist "%OLDVENV%\" rmdir /s /q "%OLDVENV%" 2>nul
if exist "%OLDRUNTIME%\" rmdir /s /q "%OLDRUNTIME%" 2>nul
echo.
"%VENV%\Scripts\python.exe" -m contextmax checkup
echo.
echo ContextMAX is installed. Open it from the Start menu or the desktop, or with "contextmax" in a new
echo terminal window. To remove it: Settings, Apps, ContextMAX, Uninstall (your projects stay).
if defined RENEWED echo If ContextMAX was open while this ran, close it and open it again.
if defined QUIET exit /b 0
echo.
echo Press a key to open ContextMAX now.
pause >nul
start "" "%CMXHOME%\ContextMAX.cmd"
exit /b 0

rem ---- Python: the private copy, checked, unpacked into %RUNTIME% ----
:private_python
set "BASEPY=%RUNTIME%\python.exe"
call :is_version && exit /b 0
set "UNPACK=%TEMP%\contextmax-python-%RANDOM%%RANDOM%"
mkdir "%UNPACK%" || exit /b 1
set "ZIP=%UNPACK%\python.zip"
if exist "%HERE%wheels\python.%PYVER%.nupkg" goto :copy_python
where curl.exe >nul 2>nul || goto :unpack_cleanup
echo Downloading Python %PYVER% (15 MB) ...
curl.exe -fsSL --retry 2 --connect-timeout 20 -y 60 -Y 1024 -o "%ZIP%" "%PYURL%" || goto :unpack_cleanup
goto :check_python
:copy_python
copy /y "%HERE%wheels\python.%PYVER%.nupkg" "%ZIP%" >nul || goto :unpack_cleanup
:check_python
set "GOT="
for /f "delims=" %%h in ('certutil -hashfile "%ZIP%" SHA256 ^| findstr /v ":"') do if not defined GOT set "GOT=%%h"
if not defined GOT goto :unpack_cleanup
set "GOT=%GOT: =%"
if /i "%GOT%"=="%PYSHA256%" goto :unpack_python
echo The Python download does not match its checksum, so it is not used.
goto :unpack_cleanup
:unpack_python
rem tar opens only names in the system's code page; names relative to the folder work whatever the user is called
pushd "%UNPACK%" || goto :unpack_failed
tar -xf python.zip tools >nul 2>nul
popd
if not exist "%UNPACK%\tools\python.exe" goto :unpack_failed
if exist "%RUNTIME%\" if not exist "%RUNTIME%\contextmax-runtime.txt" goto :runtime_taken
if exist "%OLDRUNTIME%\" rmdir /s /q "%OLDRUNTIME%"
if exist "%OLDRUNTIME%\" goto :busy
if not exist "%RUNTIME%\" goto :fresh_runtime
move "%RUNTIME%" "%OLDRUNTIME%" >nul || goto :busy
set "RENEWED=1"
:fresh_runtime
rem the marker first: a folder setup.cmd made is recognised even if the copy below is interrupted
mkdir "%RUNTIME%" || goto :unpack_failed
> "%RUNTIME%\contextmax-runtime.txt" echo Python %PYVER% for ContextMAX, unpacked by setup.cmd. uninstall.cmd removes this folder.
robocopy "%UNPACK%\tools" "%RUNTIME%" /E /MOVE /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :unpack_failed
rmdir /s /q "%UNPACK%" 2>nul
call :is_version || exit /b 1
echo Python %PYVER% is ready in "%RUNTIME%"
exit /b 0
:runtime_taken
echo The folder "%RUNTIME%" is already there and setup.cmd did not make it, so it is left alone.
goto :unpack_cleanup
:busy
set "BUSY=1"
echo The earlier ContextMAX is still in use. Close ContextMAX (its window and any contextmax command)
echo and run setup.cmd again.
goto :unpack_cleanup
:unpack_failed
echo Python %PYVER% could not be unpacked into "%RUNTIME%".
:unpack_cleanup
rmdir /s /q "%UNPACK%" 2>nul
exit /b 1

:is_version
if not exist "%BASEPY%" exit /b 1
set "CMX_WANT=%PYVER%"
"%BASEPY%" -c "import os, sys; sys.exit(sys.version.split()[0] != os.environ['CMX_WANT'])" >nul 2>nul
exit /b

rem ---- or a Python 3.11+ that this PC already has ----
:system_python
set "BASEPY="
where py >nul 2>nul && for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2^>nul') do set "BASEPY=%%p"
if defined BASEPY goto :found_python
where python >nul 2>nul && for /f "delims=" %%p in ('python -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2^>nul') do set "BASEPY=%%p"
if not defined BASEPY exit /b 1
:found_python
echo The private Python is not available; using the Python already on this PC: "%BASEPY%"
exit /b 0

rem ---- the private environment, made from that Python ----
:environment
set "CMX_BASEPY=%BASEPY%"
if exist "%OLDVENV%\" rmdir /s /q "%OLDVENV%"
if not exist "%VENV%\Scripts\python.exe" goto :new_environment
if defined RENEWED goto :renew_environment
"%VENV%\Scripts\python.exe" -c "import os, sys; sys.exit(os.path.normcase(sys._base_executable) != os.path.normcase(os.environ['CMX_BASEPY']))" >nul 2>nul && exit /b 0
:renew_environment
echo Renewing the private environment for this Python ...
rem moved aside, not cleared in place: files of a ContextMAX that is still open cannot be deleted
if exist "%OLDVENV%\" goto :busy_environment
move "%VENV%" "%OLDVENV%" >nul || goto :busy_environment
set "RENEWED=1"
:new_environment
echo Creating the private environment in "%VENV%" ...
"%BASEPY%" -m venv "%VENV%" || exit /b 1
exit /b 0
:busy_environment
echo The earlier ContextMAX is still in use. Close ContextMAX (its window and any contextmax command)
echo and run setup.cmd again.
exit /b 1

rem ---- ContextMAX and its readers: the offline installer's wheels when present, otherwise from the internet ----
:packages
echo Installing ContextMAX and its readers ...
if not exist "%HERE%wheels\requirements-lock.txt" goto :packages_online
rem every file from the wheels folder, each checked against its SHA-256 (ContextMAX itself included);
rem ContextMAX is taken out first, so a newer build of the same version replaces it
"%VENV%\Scripts\python.exe" -m pip uninstall --disable-pip-version-check -y -q contextmax >nul 2>nul
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links "%HERE%wheels" --require-hashes -r "%HERE%wheels\requirements-lock.txt" || exit /b 1
exit /b 0
:packages_online
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade "%HERE%." || exit /b 1
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade --force-reinstall --no-deps "%HERE%." >nul || exit /b 1
exit /b 0

rem ---- RapidOCR's Cyrillic model: from the offline installer, or downloaded; without it Latin script is still read ----
:ocr_models
if exist "%HERE%wheels\models\" goto :ocr_models_bundled
"%VENV%\Scripts\python.exe" -m contextmax ocr-models
exit /b 0
:ocr_models_bundled
"%VENV%\Scripts\python.exe" -m contextmax ocr-models --from "%HERE%wheels\models"
exit /b 0

:no_python
echo.
echo Python could not be installed: it could not be downloaded, and this PC has no Python 3.11 or newer.
echo Connect to the internet and run setup.cmd again, or use the offline installer: on a PC with
echo internet, make-offline-installer.cmd makes a zip that installs ContextMAX without internet.
goto :stop
:same_folder
echo setup.cmd is in "%CMXHOME%", the folder where ContextMAX installs itself and keeps your
echo projects. Put the ContextMAX download somewhere else, for example in Downloads, and run
echo setup.cmd from there. Or set CONTEXTMAX_HOME to another folder for the program and projects.
goto :stop
:fail
echo.
echo The installation did not finish; the messages above say why. The first installation needs the
echo internet, or the offline installer (make-offline-installer.cmd, on a PC with internet). If pip
echo reports a certificate error, your antivirus or company proxy inspects HTTPS: set PIP_CERT to its
echo certificate bundle and run setup.cmd again.
:stop
if not defined QUIET pause
exit /b 1
