from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


class KolorsValidationError(ValueError):
    """Raised when a generation request violates the single-GPU contract."""


@dataclass(frozen=True)
class KolorsRequest:
    prompt: str
    negative_prompt: str
    output_dir: str
    seed: int = 20260620
    width: int = 1024
    height: int = 1024
    steps: int = 30
    guidance_scale: float = 6.0
    batch_size: int = 1

    def validate(self, output_root: Path) -> Path:
        if not self.prompt.strip():
            raise KolorsValidationError("prompt 不能为空")
        if self.batch_size != 1:
            raise KolorsValidationError("单张 RTX 4090 下 Kolors 必须 batch_size=1")
        if self.width not in {512, 768, 1024} or self.height not in {512, 768, 1024}:
            raise KolorsValidationError("宽高仅允许 512、768 或 1024")
        if not 1 <= self.steps <= 50:
            raise KolorsValidationError("steps 必须在 1 到 50 之间")
        if not 0 <= self.guidance_scale <= 12:
            raise KolorsValidationError("guidance_scale 必须在 0 到 12 之间")

        root = output_root.expanduser().resolve()
        target = Path(self.output_dir).expanduser()
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        if target != root and root not in target.parents:
            raise KolorsValidationError("output_dir 必须位于 OUTPUT_DIR 内")
        return target

    def to_payload(self, output_root: Path) -> dict[str, Any]:
        target = self.validate(output_root)
        payload = asdict(self)
        payload["prompt"] = self.prompt.strip()
        payload["negative_prompt"] = self.negative_prompt.strip()
        payload["output_dir"] = str(target)
        return payload


@dataclass(frozen=True)
class KolorsResult:
    image_path: str
    metadata_path: str
    seed: int
    metrics: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "KolorsResult":
        return cls(
            image_path=str(payload["image_path"]),
            metadata_path=str(payload["metadata_path"]),
            seed=int(payload["seed"]),
            metrics=dict(payload.get("metrics") or {}),
        )


class ProcessRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        input: str,
        env: Mapping[str, str],
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        argv: list[str],
        *,
        input: str,
        env: Mapping[str, str],
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            input=input,
            text=True,
            capture_output=True,
            env=dict(env),
            timeout=timeout,
            check=False,
        )


class KolorsClient:
    def __init__(
        self,
        *,
        conda_executable: str | None = None,
        conda_env: str | None = None,
        model_path: str | None = None,
        output_root: str | Path | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.conda_executable = conda_executable or os.getenv(
            "CONDA_EXE", "conda"
        )
        self.conda_env = conda_env or os.getenv(
            "KOLORS_CONDA_ENV", "poetryedu-kolors"
        )
        self.model_path = model_path or os.getenv(
            "KOLORS_MODEL",
            "",
        )
        self.output_root = Path(
            output_root
            or os.getenv("OUTPUT_DIR", "outputs")
        ).resolve()
        self.runner = runner or SubprocessRunner()

    def command(self) -> list[str]:
        return [
            self.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.conda_env,
            "python",
            "-m",
            "backend.generation.kolors_worker",
        ]

    def generate(
        self,
        request: KolorsRequest,
        *,
        timeout_seconds: float = 900,
    ) -> KolorsResult:
        payload = request.to_payload(self.output_root)
        env = {
            **os.environ,
            "KOLORS_MODEL": self.model_path,
            "OUTPUT_DIR": str(self.output_root),
        }
        completed = self.runner.run(
            self.command(),
            input=json.dumps(payload, ensure_ascii=False),
            env=env,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Kolors 生成失败").strip()
            raise RuntimeError(message)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Kolors worker 未返回结果")
        return KolorsResult.from_payload(json.loads(lines[-1]))
