#!/usr/bin/env bash
set -euo pipefail
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Setup complete. Edit .env, then run ./run.sh"
