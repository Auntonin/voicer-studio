"""
scripts/package_release.py
==========================
One-click release packaging script for Voicer Studio.

Automates:
1. Building native launcher executable (VoicerStudio.exe) with embedded icons & version.
2. Collecting all runtime code, assets, locales, and configurations into a clean distribution.
3. Generating a ready-to-upload ZIP package (e.g. dist/VoicerStudio-v1.1.0-win64.zip).
4. Providing exact GitHub Release publishing instructions.
"""

import sys
import os
import shutil
import zipfile
import subprocess
import hashlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from config import APP_NAME, APP_VERSION
except ImportError:
    APP_NAME = "Voicer Studio"
    APP_VERSION = "1.1.0"

DIST_DIR = ROOT_DIR / "dist"
STAGE_DIR = DIST_DIR / f"VoicerStudio-v{APP_VERSION}-win64"
ZIP_OUTPUT = DIST_DIR / f"VoicerStudio-v{APP_VERSION}-win64.zip"

EXCLUDE_DIRS = {
    ".git", ".github", ".venv", ".temp", "scratch", "tests", "__pycache__",
    ".pytest_cache", ".idea", ".vscode", "dist", "build"
}

EXCLUDE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".log", ".tmp", ".bak", ".voicer", ".autosave"
}

EXCLUDE_FILES = {
    "settings.json", "crash.log", ".env"
}

def log(msg: str, status: str = "INFO"):
    icons = {"INFO": "[-]", "OK": "[+]", "WARN": "[!]", "ERR": "[x]"}
    print(f"{icons.get(status, '[-]')} {msg}")

def step_compile_exe() -> bool:
    log("Step 1: Compiling native launcher (VoicerStudio.exe)...", "INFO")
    build_script = ROOT_DIR / "scripts" / "build_exe.py"
    if build_script.exists():
        res = subprocess.run([sys.executable, str(build_script)], cwd=str(ROOT_DIR))
        if res.returncode != 0:
            log("build_exe.py failed or GCC not found. Checking existing VoicerStudio.exe...", "WARN")
            if (ROOT_DIR / "VoicerStudio.exe").exists():
                log("Using existing VoicerStudio.exe in workspace root.", "OK")
                return True
            return False
        return True
    return False

def step_stage_files():
    log(f"Step 2: Staging release files into {STAGE_DIR.name}...", "INFO")
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Core items to copy
    include_paths = [
        "VoicerStudio.exe",
        "main.py",
        "config.py",
        "requirements.txt",
        "settings.example.json",
        "README.md",
        "LICENSE",
        "assets",
        "core",
        "gui",
        "locales",
        "scripts",
    ]

    for item_name in include_paths:
        src = ROOT_DIR / item_name
        dst = STAGE_DIR / item_name
        if not src.exists():
            continue

        if src.is_file():
            shutil.copy2(src, dst)
        elif src.is_dir():
            shutil.copytree(
                src, dst,
                ignore=lambda dirpath, contents: [
                    c for c in contents
                    if c in EXCLUDE_DIRS
                    or any(c.endswith(ext) for ext in EXCLUDE_EXTENSIONS)
                    or c in EXCLUDE_FILES
                ]
            )

    log("Staging complete.", "OK")

def step_create_zip():
    log(f"Step 3: Creating release archive {ZIP_OUTPUT.name}...", "INFO")
    if ZIP_OUTPUT.exists():
        ZIP_OUTPUT.unlink()

    with zipfile.ZipFile(ZIP_OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(STAGE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if any(f.endswith(ext) for ext in EXCLUDE_EXTENSIONS) or f in EXCLUDE_FILES:
                    continue
                file_path = Path(root) / f
                arcname = file_path.relative_to(STAGE_DIR.parent)
                zf.write(file_path, arcname)

    size_mb = ZIP_OUTPUT.stat().st_size / (1024 * 1024)
    log(f"Release ZIP created successfully: {ZIP_OUTPUT.name} ({size_mb:.2f} MB)", "OK")
    _write_sha256(ZIP_OUTPUT)

    # Also copy standalone VoicerStudio.exe directly into dist/ for users who just want the exe update
    exe_src = ROOT_DIR / "VoicerStudio.exe"
    if exe_src.exists():
        dist_exe = DIST_DIR / "VoicerStudio.exe"
        shutil.copy2(exe_src, dist_exe)
        log(f"Copied standalone executable: {dist_exe.name}", "OK")
        _write_sha256(dist_exe)


def _write_sha256(path: Path) -> Path:
    """Create the checksum sidecar required by the in-app updater."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_path = path.with_name(f"{path.name}.sha256")
    checksum_path.write_text(f"{digest.hexdigest()}  {path.name}\n", encoding="ascii")
    log(f"Created integrity checksum: {checksum_path.name}", "OK")
    return checksum_path

def print_instructions():
    print("\n" + "=" * 76)
    print(f"       VOICER STUDIO v{APP_VERSION} — RELEASE PACKAGE READY!")
    print("=" * 76)
    print(f"  Files created in: {DIST_DIR.resolve()}")
    print(f"  1. {ZIP_OUTPUT.name} (Full update package for all users)")
    print(f"  2. VoicerStudio.exe (Standalone executable launcher)")
    print("\nHow to publish update to all friends automatically:")
    print("--------------------------------------------------")
    print(f"1. Open GitHub: https://github.com/Auntonin/voicer-studio/releases/new")
    print(f"2. Set Tag version: v{APP_VERSION}")
    print(f"3. Set Release title: Voicer Studio v{APP_VERSION}")
    print(f"4. Drag & drop '{ZIP_OUTPUT.name}' and '{ZIP_OUTPUT.name}.sha256' into the release assets area.")
    print("5. Click 'Publish release'. The checksum is required for in-app updates.")
    print("\nDone! Any friend opening VoicerStudio.exe will now see:")
    print("  'มีเวอร์ชันใหม่ของ Voicer Studio พร้อมให้อัปเดต!'")
    print("  and can update in 1 click automatically!\n" + "=" * 76)

if __name__ == "__main__":
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    step_compile_exe()
    step_stage_files()
    step_create_zip()
    print_instructions()
