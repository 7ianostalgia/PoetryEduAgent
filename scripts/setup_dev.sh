#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "[ERROR] Python >= 3.10 is required."
  exit 1
}

echo "[OK] Python: $("$PYTHON_BIN" --version 2>&1)"

if [[ ! -x .venv/bin/python ]]; then
  echo "[INFO] Creating .venv"
  "$PYTHON_BIN" -m venv .venv
else
  echo "[OK] Reusing .venv"
fi

echo "[INFO] Installing requirements-dev.txt"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

if [[ ! -f .env ]]; then
  echo "[INFO] .env is not present."
  echo "       Run: cp .env.example .env"
fi

echo "[OK] dev environment is ready."
echo "Next: bash scripts/start_dev.sh"
