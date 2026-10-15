@echo off
rem ContextMAX.cmd - open the ContextMAX window: choose folders, build, open the maps.
rem It uses the program that setup.cmd installed; the first time, when there is none, it runs
rem setup.cmd itself. In a developer checkout it falls back to the checkout's .venv.
setlocal EnableExtensions DisableDelayedExpansion
set "CMXHOME=%USERPROFILE%\ContextMAX"
if defined CONTEXTMAX_HOME set "CMXHOME=%CONTEXTMAX_HOME%"
set "PYEXE=%CMXHOME%\.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :run
set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :run
echo ContextMAX is not installed yet: setting it up first (one time only).
echo.
call "%~dp0setup.cmd" /quiet
if errorlevel 1 goto :failed
set "PYEXE=%CMXHOME%\.venv\Scripts\python.exe"
:run
title ContextMAX
"%PYEXE%" -m contextmax panel %*
exit /b
:failed
echo.
echo ContextMAX could not be set up; the messages above say why.
pause
exit /b 1
