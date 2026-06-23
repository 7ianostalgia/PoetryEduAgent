#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
CONDA_EXE="${CONDA_EXE:-conda}"
QWEN_CONDA_ENV="${QWEN_CONDA_ENV:-poetryedu-qwen14b-awq}"
KOLORS_CONDA_ENV="${KOLORS_CONDA_ENV:-poetryedu-kolors}"
VISION_CONDA_ENV="${VISION_CONDA_ENV:-poetryedu-qwen-vl}"

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "[ERROR] Python >= 3.10 is required."
  exit 1
}

command -v "$CONDA_EXE" >/dev/null 2>&1 || {
  echo "[ERROR] Conda is unavailable: $CONDA_EXE"
  echo "        Set CONDA_EXE or install Conda first."
  exit 1
}

if [[ ! -x .venv/bin/python ]]; then
  echo "[INFO] Creating main service .venv"
  "$PYTHON_BIN" -m venv .venv
else
  echo "[OK] Reusing main service .venv"
fi

echo "[INFO] Installing main service dependencies"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

ensure_conda_env() {
  local env_name="$1"
  local requirement_file="$2"

  if "$CONDA_EXE" env list --json | .venv/bin/python -c \
    'import json, pathlib, sys; name=sys.argv[1]; data=json.load(sys.stdin); raise SystemExit(0 if name in {pathlib.Path(p).name for p in data.get("envs", [])} else 1)' \
    "$env_name"; then
    echo "[OK] Reusing Conda environment: $env_name"
  else
    echo "[INFO] Creating Conda environment: $env_name"
    "$CONDA_EXE" create -n "$env_name" python=3.10 -y
  fi

  echo "[INFO] Installing $requirement_file into $env_name"
  "$CONDA_EXE" run -n "$env_name" python -m pip install -r "$requirement_file"
}

ensure_conda_env "$QWEN_CONDA_ENV" "environments/qwen14b-awq.txt"
ensure_conda_env "$KOLORS_CONDA_ENV" "environments/kolors.txt"
ensure_conda_env "$VISION_CONDA_ENV" "environments/qwen-vl.txt"

if [[ ! -f .env ]]; then
  echo "[INFO] .env is not present."
  echo "       Run: cp .env.example .env"
  echo "       Then configure RUN_MODE=gpu and all model paths."
fi

echo "[OK] gpu environments are ready."
echo "Next: bash scripts/start_gpu.sh"
