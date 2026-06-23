from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


RunMode = Literal["dev", "gpu"]


def _run_mode() -> RunMode:
    value = os.getenv("RUN_MODE", "dev").strip().lower()
    if value not in {"dev", "gpu"}:
        raise ValueError("RUN_MODE must be either 'dev' or 'gpu'")
    return value  # type: ignore[return-value]


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_mode: RunMode = "dev"
    dev_stage_delay_seconds: float = Field(default=0.03, ge=0)
    host: str = "0.0.0.0"
    port: int = Field(default=7860, ge=1, le=65535)
    frontend_static_dir: Path
    database_path: Path
    runtime_database_path: Path
    output_dir: Path


def load_settings() -> Settings:
    return Settings(
        run_mode=_run_mode(),
        dev_stage_delay_seconds=float(
            os.getenv("DEV_STAGE_DELAY_SECONDS", "0.03")
        ),
        host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        frontend_static_dir=Path(
            os.getenv(
                "FRONTEND_STATIC_DIR",
                str(PROJECT_ROOT / "frontend" / "static"),
            )
        ),
        database_path=Path(
            os.getenv(
                "POETRY_DB_PATH",
                str(PROJECT_ROOT / "data" / "poetry_edu.db"),
            )
        ),
        runtime_database_path=Path(
            os.getenv(
                "POETRY_RUNTIME_DB_PATH",
                str(PROJECT_ROOT / "data" / "runtime" / "learning_runtime.db"),
            )
        ),
        output_dir=Path(
            os.getenv("OUTPUT_DIR", str(PROJECT_ROOT / "outputs"))
        ),
    )


settings = load_settings()
