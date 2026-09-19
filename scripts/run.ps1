Set-Location $PSScriptRoot
if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" main.py
} else {
    python main.py
}
