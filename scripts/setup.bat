@echo off
cd /d "%~dp0.."
setlocal enabledelayedexpansion

:: ============================================================
:: The Choice Voicer Dialogue Extractor — Windows Setup
:: ============================================================
:: Requires: Python 3.10+ and FFmpeg in PATH
:: Run this script once before launching the application.
:: ============================================================

title The Choice Voicer Dialogue Extractor — Setup

echo.
echo  ==========================================
echo   The Choice Voicer Dialogue Extractor
echo   Setup Script for Windows
echo  ==========================================
echo.

:: ── Check Python ──────────────────────────────────────────
echo [1/7] Checking Python version...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10 or 3.11.
    echo         Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo        Found Python %PYVER%

:: Check Python >= 3.10
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 (
    echo [ERROR] Python 3.10 or higher is required. You have %PYVER%.
    pause
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 (
    echo [ERROR] Python 3.10 or higher is required. You have %PYVER%.
    pause
    exit /b 1
)
echo        [OK] Python %PYVER%

:: ── Check FFmpeg ──────────────────────────────────────────
echo.
echo [2/7] Checking FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFmpeg not found in PATH.
    echo.
    echo         Option A: Install via winget:
    echo           winget install Gyan.FFmpeg
    echo.
    echo         Option B: Download manually:
    echo           https://www.gyan.dev/ffmpeg/builds/
    echo           Then add ffmpeg\bin to your PATH.
    echo.
    pause
    exit /b 1
)
echo        [OK] FFmpeg found

:: ── Create Virtual Environment ────────────────────────────
echo.
echo [3/7] Creating virtual environment (.venv)...
set VENV_HEALTHY=0
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import sys; assert sys.prefix != sys.base_prefix" >nul 2>&1
    if not errorlevel 1 set VENV_HEALTHY=1
)
if "%VENV_HEALTHY%"=="0" (
    if exist ".venv\" (
        echo        [INFO] Existing .venv is invalid; recreating it...
        rmdir /s /q ".venv"
    )
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo        [OK] .venv created
) else (
    echo        [OK] Existing .venv is healthy
)

:: ── Activate venv ─────────────────────────────────────────
echo.
echo [4/7] Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)
echo        [OK] Activated

:: ── Upgrade pip ───────────────────────────────────────────
echo.
echo [5/7] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo        [OK] pip upgraded

:: ── Install PyTorch (CUDA 12.1 or CPU fallback) ──────────
echo.
echo [6/7] Installing PyTorch...
echo.
echo        Detecting GPU...
python -c "import subprocess; r=subprocess.run(['nvidia-smi'],capture_output=True); exit(0 if r.returncode==0 else 1)" >nul 2>&1
if errorlevel 1 (
    echo        [INFO] No NVIDIA GPU detected — installing CPU-only PyTorch.
    echo        [INFO] Voice separation (Demucs) will be slower on CPU.
    pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cpu --quiet
) else (
    echo        [INFO] NVIDIA GPU detected — installing CUDA 12.1 PyTorch.
    pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --quiet
)
echo        [OK] PyTorch installed

:: ── Install remaining requirements ────────────────────────
echo.
echo [7/7] Installing project requirements...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [WARNING] Some packages may have failed. Check output above.
) else (
    echo        [OK] All packages installed
)

:: ── Ensure Default Configuration ─────────────────────────
if not exist "settings.json" (
    if exist "settings.example.json" (
        copy "settings.example.json" "settings.json" >nul
        echo        [OK] Initialized default settings.json
    )
)

:: ── Post-install info ─────────────────────────────────────
echo.
echo  ==========================================
echo   Setup Complete!
echo  ==========================================
echo.
echo  To launch the application:
echo    start.bat
echo    -- OR --
echo    run.bat
echo    -- OR --
echo    .venv\Scripts\python.exe main.py
echo.
pause
