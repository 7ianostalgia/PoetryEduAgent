#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _resolved(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _info(message: str) -> None:
    print(f"[INFO] {message}")


def _error(message: str) -> None:
    print(f"[ERROR] {message}")


def _check_python(errors: list[str]) -> None:
    if sys.version_info < (3, 10):
        errors.append(
            f"Python >= 3.10 is required; current version is "
            f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        return
    _ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")


def _check_port(host: str, port: int, errors: list[str]) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError as exc:
        errors.append(f"PORT {port} is unavailable on HOST {host}: {exc}")
        return
    _ok(f"HOST={host}, PORT={port}")


def _conda_envs(conda_exe: str) -> set[str]:
    completed = subprocess.run(
        [conda_exe, "env", "list", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip() or "unable to list Conda environments"
        )
    payload = json.loads(completed.stdout)
    return {Path(item).name for item in payload.get("envs", [])}


def validate(mode_override: str | None = None) -> int:
    errors: list[str] = []
    _check_python(errors)

    if not ENV_FILE.is_file():
        _error(f".env does not exist: {ENV_FILE}")
        print("Please run: cp .env.example .env")
        return 1

    file_values = _read_env(ENV_FILE)
    values = {**file_values, **os.environ}
    mode = (mode_override or values.get("RUN_MODE", "")).strip().lower()
    if mode not in {"dev", "gpu"}:
        errors.append("RUN_MODE must be dev or gpu; update RUN_MODE in .env")
    else:
        _ok(f"RUN_MODE={mode}")

    host = values.get("HOST", "0.0.0.0").strip()
    if not host:
        errors.append("HOST is empty; update HOST in .env")
        host = "0.0.0.0"
    try:
        port = int(values.get("PORT", "7860"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        errors.append("PORT must be an integer between 1 and 65535")
        port = 7860
    if not errors:
        _check_port(host, port, errors)

    poetry_db_value = values.get("POETRY_DB_PATH", "").strip()
    if not poetry_db_value:
        errors.append("POETRY_DB_PATH is empty; update it in .env")
    else:
        poetry_db = _resolved(poetry_db_value)
        if not poetry_db.is_file():
            errors.append(
                f"POETRY_DB_PATH does not exist: {poetry_db}. "
                "Please update POETRY_DB_PATH in .env"
            )
        else:
            try:
                with sqlite3.connect(poetry_db) as conn:
                    result = conn.execute("PRAGMA integrity_check").fetchone()
                if not result or str(result[0]).lower() != "ok":
                    errors.append(
                        f"POETRY_DB_PATH failed integrity_check: {poetry_db}"
                    )
                else:
                    _ok(f"POETRY_DB_PATH={poetry_db}")
            except sqlite3.Error as exc:
                errors.append(f"POETRY_DB_PATH is not a valid SQLite file: {exc}")

    runtime_value = values.get("POETRY_RUNTIME_DB_PATH", "").strip()
    if not runtime_value:
        errors.append("POETRY_RUNTIME_DB_PATH is empty; update it in .env")
    else:
        runtime_db = _resolved(runtime_value)
        if runtime_db.exists() and not runtime_db.is_file():
            errors.append(
                f"POETRY_RUNTIME_DB_PATH is not a file: {runtime_db}"
            )
        else:
            runtime_db.parent.mkdir(parents=True, exist_ok=True)
            _ok(f"POETRY_RUNTIME_DB_PATH={runtime_db}")

    output_value = values.get("OUTPUT_DIR", "").strip()
    if not output_value:
        errors.append("OUTPUT_DIR is empty; update it in .env")
    else:
        output_dir = _resolved(output_value)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            _ok(f"OUTPUT_DIR={output_dir}")
        except OSError as exc:
            errors.append(f"OUTPUT_DIR cannot be created: {output_dir}: {exc}")

    if mode == "gpu":
        for name in ("LOCAL_LLM_MODEL", "KOLORS_MODEL", "VISION_MODEL"):
            value = values.get(name, "").strip()
            if not value:
                errors.append(f"{name} is empty; update {name} in .env")
                continue
            path = _resolved(value)
            if not path.is_dir():
                errors.append(
                    f"{name} does not exist: {path}. Please update {name} in .env"
                )
            else:
                _ok(f"{name}={path}")

        if values.get("DEEPSEEK_API_KEY", "").strip():
            _ok("DEEPSEEK_API_KEY is configured")
        else:
            _info(
                "DEEPSEEK_API_KEY is not configured; "
                "DeepSeek-V4-Flash review will use the local Qwen fallback"
            )

        conda_value = values.get("CONDA_EXE", "conda").strip() or "conda"
        conda_exe = shutil.which(conda_value)
        if conda_exe is None and Path(conda_value).is_file():
            conda_exe = str(Path(conda_value).resolve())
        if conda_exe is None:
            errors.append(
                f"CONDA_EXE is unavailable: {conda_value}. "
                "Please update CONDA_EXE in .env"
            )
        else:
            _ok(f"CONDA_EXE={conda_exe}")
            try:
                available = _conda_envs(conda_exe)
                for variable, default in (
                    ("QWEN_CONDA_ENV", "poetryedu-qwen14b-awq"),
                    ("KOLORS_CONDA_ENV", "poetryedu-kolors"),
                    ("VISION_CONDA_ENV", "poetryedu-qwen-vl"),
                ):
                    env_name = values.get(variable, default).strip() or default
                    if env_name not in available:
                        errors.append(
                            f"{variable} does not exist: {env_name}. "
                            "Run bash scripts/setup_gpu.sh"
                        )
                    else:
                        _ok(f"{variable}={env_name}")
            except (RuntimeError, json.JSONDecodeError) as exc:
                errors.append(f"Unable to inspect Conda environments: {exc}")

    if errors:
        for message in errors:
            _error(message)
        return 1

    print(f"[OK] Environment is ready for RUN_MODE={mode}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate PoetryEduAgent dev/gpu runtime configuration"
    )
    parser.add_argument("--mode", choices=("dev", "gpu"))
    args = parser.parse_args()
    try:
        return validate(args.mode)
    except Exception as exc:
        _error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
