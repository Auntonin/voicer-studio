@echo off
cd /d "%~dp0"
title Voicer Studio Launcher

echo ============================================================
echo   Voicer Studio Launcher
echo ============================================================
echo.

:: ── 1. Ensure configuration exists ───────────────────────────
if not exist "settings.json" (
    if exist "settings.example.json" (
        echo [INFO] First-time launch: initializing settings.json from template...
        copy "settings.example.json" "settings.json" >nul
        echo [OK] settings.json created successfully.
    ) else (
        echo [WARNING] settings.example.json not found!
    )
)

:: ── 2. Ensure virtual environment exists ─────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Python virtual environment (.venv) not found.
    echo [INFO] Starting automatic setup... (this only runs once)
    echo.
    call setup.bat
    if errorlevel 1 (
        echo.
        echo [ERROR] Setup encountered an issue. Please review the output above.
        pause
        exit /b 1
    )
)

:: ── 3. Launch Application ─────────────────────────────────────
echo [INFO] Starting Voicer Studio...
if exist ".venv\Scripts\python.exe" (
    call .venv\Scripts\activate.bat
    python main.py %*
) else (
    python main.py %*
)

if errorlevel 1 (
    echo.
    echo [ERROR] Voicer Studio closed with error code %errorlevel%.
    pause
)
