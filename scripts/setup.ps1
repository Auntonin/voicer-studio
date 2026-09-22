# ============================================================
# The Choice Voicer Dialogue Extractor - PowerShell Setup
# ============================================================
# Run: powershell -ExecutionPolicy Bypass -File setup.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "The Choice Voicer Dialogue Extractor - Setup"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  The Choice Voicer Dialogue Extractor" -ForegroundColor Cyan
Write-Host "  Setup Script for Windows (PowerShell)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check Python ──────────────────────────────────────────
Write-Host "[1/7] Checking Python version..." -ForegroundColor Yellow
try {
    $pyver = python --version 2>&1
    Write-Host "       Found: $pyver" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+" -ForegroundColor Red
    Write-Host "        Download: https://www.python.org/downloads/" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$verStr = (python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") 2>&1
$verParts = $verStr.Trim().Split(".")
if ([int]$verParts[0] -lt 3 -or ([int]$verParts[0] -eq 3 -and [int]$verParts[1] -lt 10)) {
    Write-Host "[ERROR] Python 3.10 or higher required. Found: $verStr" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "       [OK] Python $verStr" -ForegroundColor Green

# ── Check FFmpeg ──────────────────────────────────────────
Write-Host ""
Write-Host "[2/7] Checking FFmpeg..." -ForegroundColor Yellow
$ffmpegInstalled = $false
try {
    $null = ffmpeg -version 2>&1
    $ffmpegInstalled = $true
    Write-Host "       [OK] FFmpeg found" -ForegroundColor Green
} catch {
    $ffmpegInstalled = $false
}

if (-not $ffmpegInstalled) {
    Write-Host "       [INFO] FFmpeg not found — attempting automatic installation via Winget..." -ForegroundColor Yellow
    try {
        winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements --silent
        Write-Host "       [OK] FFmpeg installed via Winget" -ForegroundColor Green
    } catch {
        Write-Host "       [WARNING] Could not auto-install FFmpeg via Winget." -ForegroundColor Yellow
        Write-Host "       Note: Voicer Studio will auto-download standalone FFmpeg on first launch if missing." -ForegroundColor Cyan
    }
}

# ── Create Virtual Environment ────────────────────────────
Write-Host ""
Write-Host "[3/7] Creating virtual environment (.venv)..." -ForegroundColor Yellow
$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
$venvHealthy = $false
if (Test-Path $venvPython) {
    & $venvPython -c "import sys; assert sys.prefix != sys.base_prefix" 2>$null
    $venvHealthy = ($LASTEXITCODE -eq 0)
}
if (-not $venvHealthy) {
    if (Test-Path ".venv") {
        Write-Host "       [INFO] Existing .venv is invalid; recreating it..." -ForegroundColor Yellow
        Remove-Item -LiteralPath ".venv" -Recurse -Force
    }
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "       [OK] .venv created" -ForegroundColor Green
} else {
    Write-Host "       [OK] Existing .venv is healthy" -ForegroundColor Green
}

# ── Activate venv ─────────────────────────────────────────
Write-Host ""
Write-Host "[4/7] Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1
Write-Host "       [OK] Activated" -ForegroundColor Green

# ── Upgrade pip ───────────────────────────────────────────
Write-Host ""
Write-Host "[5/7] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
Write-Host "       [OK] pip upgraded" -ForegroundColor Green

# ── Install PyTorch ───────────────────────────────────────
Write-Host ""
Write-Host "[6/7] Installing PyTorch..." -ForegroundColor Yellow

$hasGPU = $false
try {
    $null = nvidia-smi 2>&1
    if ($LASTEXITCODE -eq 0) { $hasGPU = $true }
} catch {}

if ($hasGPU) {
    Write-Host "       [INFO] NVIDIA GPU detected - installing CUDA 12.1 PyTorch" -ForegroundColor Cyan
    pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --quiet
} else {
    Write-Host "       [INFO] No NVIDIA GPU detected - installing CPU PyTorch" -ForegroundColor Yellow
    Write-Host "       [INFO] Voice separation (Demucs) will be slower on CPU" -ForegroundColor Yellow
    pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cpu --quiet
}
Write-Host "       [OK] PyTorch installed" -ForegroundColor Green

# ── Install Requirements ──────────────────────────────────
Write-Host ""
Write-Host "[7/7] Installing project requirements..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Some packages may have failed. Check output." -ForegroundColor Yellow
} else {
    Write-Host "       [OK] All packages installed" -ForegroundColor Green
}

# ── Create run.ps1 ────────────────────────────────────────
$runScript = @"
& .\.venv\Scripts\Activate.ps1
python main.py
"@
Set-Content -Path "run.ps1" -Value $runScript -Encoding UTF8
Write-Host "       [OK] Created run.ps1" -ForegroundColor Green

# ── Create run.bat (simple launcher) ──────────────────────
$runBat = "@echo off`r`npowershell -ExecutionPolicy Bypass -File run.ps1`r`n"
Set-Content -Path "run.bat" -Value $runBat -Encoding ASCII
Write-Host "       [OK] Created run.bat" -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT - Before first use:" -ForegroundColor Yellow
Write-Host ""
Write-Host "[Speaker Diarization - pyannote.audio]" -ForegroundColor White
Write-Host "  1. Create account at https://huggingface.co" -ForegroundColor Gray
Write-Host "  2. Accept model license:" -ForegroundColor Gray
Write-Host "     https://huggingface.co/pyannote/speaker-diarization-3.1" -ForegroundColor Cyan
Write-Host "  3. Generate token: https://huggingface.co/settings/tokens" -ForegroundColor Gray
Write-Host "  4. Enter token in app Settings (first launch)" -ForegroundColor Gray
Write-Host ""
Write-Host "[Whisper Models - auto-downloaded on first use]" -ForegroundColor White
Write-Host "  tiny   ~75MB    | base  ~142MB | small  ~466MB" -ForegroundColor Gray
Write-Host "  medium ~1.5GB   | large-v3 ~3GB (recommended)" -ForegroundColor Gray
Write-Host ""
Write-Host "To launch: run.bat  or  powershell -File run.ps1" -ForegroundColor Cyan
Write-Host ""
