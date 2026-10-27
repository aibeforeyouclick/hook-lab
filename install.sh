#!/usr/bin/env sh
# Linux / macOS. Creates .venv, installs the dependencies and checks ffmpeg.
# Use a Python version that PyTorch supports (3.12 is what this project is tested with).
set -eu
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
command -v ffmpeg >/dev/null 2>&1 || echo "ffmpeg not found: install it (apt install ffmpeg / brew install ffmpeg)."
.venv/bin/python -m hooklab doctor
