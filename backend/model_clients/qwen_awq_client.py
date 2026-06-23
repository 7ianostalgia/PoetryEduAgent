from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol


class QwenRequestError(ValueError):
    """Raised when a text request exceeds the server inference guardrails."""


@dataclass(frozen=True)
class QwenTextRequest:
    task_name: str
    system_prompt: str
    user_prompt: str
    output_schema: Mapping[str, Any]
    max_input_tokens: int = 6144
    max_new_tokens: int = 1536
    temperature: float = 0.2
    top_p: float = 0.9
    seed: int = 20260620

    def validate(self) -> None:
        if not self.task_name.strip():
            raise QwenRequestError("task_name 不能为空")
        if not self.user_prompt.strip():
            raise QwenRequestError("user_prompt 不能为空")
        if not 256 <= self.max_input_tokens <= 8192:
            raise QwenRequestError("max_input_tokens 必须在 256 到 8192 之间")
        if not 64 <= self.max_new_tokens <= 2048:
            raise QwenRequestError("max_new_tokens 必须在 64 到 2048 之间")
        if not 0 <= self.temperature <= 1:
            raise QwenRequestError("temperature 必须在 0 到 1 之间")
        if not 0 < self.top_p <= 1:
            raise QwenRequestError("top_p 必须在 0 到 1 之间")
        if not isinstance(self.output_schema, Mapping) or not self.output_schema:
            raise QwenRequestError("output_schema 必须是非空 JSON Schema")

    def to_payload(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["output_schema"] = dict(self.output_schema)
        return payload


@dataclass(frozen=True)
class QwenTextResult:
    task_name: str
    output: Mapping[str, Any]
    raw_text: str
    metrics: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "QwenTextResult":
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


class QwenAwqClient:
    def __init__(
        self,
        *,
        conda_executable: str | None = None,
        conda_env: str | None = None,
        model_path: str | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.conda_executable = conda_executable or os.getenv(
            "CONDA_EXE", "conda"
        )
        self.conda_env = conda_env or os.getenv(
            "QWEN_CONDA_ENV", "poetryedu-qwen14b-awq"
        )
        self.model_path = model_path or os.getenv(
            "LOCAL_LLM_MODEL",
            "",
        )
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
            "backend.model_clients.qwen_awq_worker",
        ]

    def run_text(
        self,
        request: QwenTextRequest,
        *,
        timeout_seconds: float = 900,
    ) -> QwenTextResult:
        completed = self.runner.run(
            self.command(),
            input=json.dumps(request.to_payload(), ensure_ascii=False),
            env={**os.environ, "LOCAL_LLM_MODEL": self.model_path},
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Qwen 推理失败").strip()
            raise RuntimeError(message)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Qwen worker 未返回结果")
        return QwenTextResult.from_payload(json.loads(lines[-1]))

    def run_batch(
        self,
        requests: list[QwenTextRequest],
        *,
        timeout_seconds: float = 1200,
    ) -> list[QwenTextResult]:
        if not requests:
            raise QwenRequestError("批量请求不能为空")
        completed = self.runner.run(
            self.command(),
            input=json.dumps(
                {"requests": [request.to_payload() for request in requests]},
                ensure_ascii=False,
            ),
            env={**os.environ, "LOCAL_LLM_MODEL": self.model_path},
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Qwen 批量推理失败").strip()
            raise RuntimeError(message)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Qwen worker 未返回批量结果")
        payload = json.loads(lines[-1])
        return [
            QwenTextResult.from_payload(item)
            for item in payload["results"]
        ]
