@echo off
chcp 65001 >nul
title Voicer Studio — Package Release
echo ======================================================================
echo                Voicer Studio — Package Release Generator
echo ======================================================================
echo.

set PYTHON_CMD=python
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
)

"%PYTHON_CMD%" scripts\package_release.py

echo.
pause
