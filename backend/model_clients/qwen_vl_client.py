from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol


class QwenVisionRequestError(ValueError):
    """Raised when an image review request violates safety limits."""


@dataclass(frozen=True)
class QwenVisionRequest:
    task_name: str
    image_path: str
    prompt: str
    output_schema: Mapping[str, Any] | None = None
    response_mode: Literal["json", "text"] = "json"
    min_pixels: int = 256 * 28 * 28
    max_pixels: int = 1280 * 28 * 28
    max_new_tokens: int = 512

    def to_payload(self, output_root: Path) -> dict[str, Any]:
        if not self.task_name.strip() or not self.prompt.strip():
            raise QwenVisionRequestError("task_name 和 prompt 不能为空")
        if not 64 <= self.max_new_tokens <= 1024:
            raise QwenVisionRequestError("max_new_tokens 必须在 64 到 1024 之间")
        if not 28 * 28 <= self.min_pixels <= self.max_pixels:
            raise QwenVisionRequestError("视觉像素范围无效")
        if self.max_pixels > 1280 * 28 * 28:
            raise QwenVisionRequestError("max_pixels 超过单卡安全上限")
        if self.response_mode == "json" and not self.output_schema:
            raise QwenVisionRequestError("output_schema 不能为空")

        root = output_root.expanduser().resolve()
        image = Path(self.image_path).expanduser().resolve()
        if image != root and root not in image.parents:
            raise QwenVisionRequestError("image_path 必须位于 OUTPUT_DIR 内")
        if not image.is_file():
            raise QwenVisionRequestError(f"图片不存在：{image}")

        payload = asdict(self)
        payload["image_path"] = str(image)
        payload["output_schema"] = (
            dict(self.output_schema) if self.output_schema else None
        )
        return payload


@dataclass(frozen=True)
class QwenVisionResult:
    task_name: str
    output: Mapping[str, Any]
    raw_text: str
    metrics: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "QwenVisionResult":
        return cls(
            task_name=str(payload["task_name"]),
            output=dict(payload["output"]),
            raw_text=str(payload["raw_text"]),
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


class QwenVisionClient:
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
            "VISION_CONDA_ENV", "poetryedu-qwen-vl"
        )
        self.model_path = model_path or os.getenv(
            "VISION_MODEL",
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
            "backend.model_clients.qwen_vl_worker",
        ]

    def review(
        self,
        request: QwenVisionRequest,
        *,
        timeout_seconds: float = 900,
    ) -> QwenVisionResult:
        completed = self.runner.run(
            self.command(),
            input=json.dumps(
                request.to_payload(self.output_root),
                ensure_ascii=False,
            ),
            env={
                **os.environ,
                "VISION_MODEL": self.model_path,
                "OUTPUT_DIR": str(self.output_root),
            },
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Qwen-VL 审核失败").strip()
            raise RuntimeError(message)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Qwen-VL worker 未返回结果")
        return QwenVisionResult.from_payload(json.loads(lines[-1]))
