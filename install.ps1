# Windows PowerShell. Creates .venv, installs the dependencies and checks ffmpeg.
# Use a Python version that PyTorch supports (3.12 is what this project is tested with).
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Host "ffmpeg not found: install it (for example: winget install ffmpeg) and reopen the terminal." }
.\.venv\Scripts\python.exe -m hooklab doctor
