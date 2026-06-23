#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "[ERROR] .env does not exist."
  echo "        Run: cp .env.example .env"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "[ERROR] .venv is not ready."
  echo "        Run: bash scripts/setup_dev.sh"
  exit 1
fi

set -a
source .env
set +a
export RUN_MODE=dev

.venv/bin/python scripts/check_env.py --mode dev

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-7860}"

echo "[OK] RUN_MODE=dev"
echo "Frontend: http://localhost:${PORT}"
echo "Backend:  http://localhost:${PORT}"
echo "API Docs: http://localhost:${PORT}/docs"

exec .venv/bin/uvicorn backend.main:app --host "$HOST" --port "$PORT"
