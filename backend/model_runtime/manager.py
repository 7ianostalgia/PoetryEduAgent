from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, MutableMapping, Optional, Protocol, Union
from uuid import uuid4


class ModelRuntimeError(RuntimeError):
    """Base exception for model runtime planning and scheduling failures."""


class RequestValidationError(ValueError):
    """Raised when a model request exceeds runtime guardrails."""


class ModelKey(str, Enum):
    QWEN14B_AWQ = "qwen14b_awq"
    KOLORS = "kolors"
    QWEN_VL = "qwen_vl"


class TaskStage(str, Enum):
    """Known model-backed stages.

    Values intentionally mirror orchestration labels instead of Python names so
    command plans can be compared in tests and logs without translation.
    """

    TEXT_ANALYSIS = "TEXT_ANALYSIS"
    IMAGE_GENERATION = "IMAGE_GENERATION"
    VISION_REVIEW = "VISION_REVIEW"
    LOCAL_REVIEW_D2 = "LOCAL_REVIEW_D2"
    UNLOAD = "UNLOAD"


@dataclass(frozen=True)
class ModelSpec:
    key: ModelKey
    conda_env: str
    conda_env_variable: str
    path_env: str
    default_stage: TaskStage


MODEL_SPECS: Mapping[ModelKey, ModelSpec] = {
    ModelKey.QWEN14B_AWQ: ModelSpec(
        key=ModelKey.QWEN14B_AWQ,
        conda_env="poetryedu-qwen14b-awq",
        conda_env_variable="QWEN_CONDA_ENV",
        path_env="LOCAL_LLM_MODEL",
        default_stage=TaskStage.TEXT_ANALYSIS,
    ),
    ModelKey.KOLORS: ModelSpec(
        key=ModelKey.KOLORS,
        conda_env="poetryedu-kolors",
        conda_env_variable="KOLORS_CONDA_ENV",
        path_env="KOLORS_MODEL",
        default_stage=TaskStage.IMAGE_GENERATION,
    ),
    ModelKey.QWEN_VL: ModelSpec(
        key=ModelKey.QWEN_VL,
        conda_env="poetryedu-qwen-vl",
        conda_env_variable="VISION_CONDA_ENV",
        path_env="VISION_MODEL",
        default_stage=TaskStage.VISION_REVIEW,
    ),
}

MAX_INPUT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 2048
MAX_TOTAL_TOKENS = 10000
MAX_VISION_PIXELS = 1_572_864  # 1536 * 1024; conservative runtime cap.


@dataclass(frozen=True)
class ModelRequest:
    model_key: Union[ModelKey, str]
    stage: Union[TaskStage, str]
    payload: Mapping[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    max_new_tokens: int = 512
    visual_pixels: Optional[int] = None
    batch_size: int = 1
    timeout_seconds: float = 60.0
    request_id: str = field(default_factory=lambda: uuid4().hex)

    def normalized(self) -> "ModelRequest":
        model_key = ModelKey(self.model_key)
        stage = TaskStage(self.stage)
        request = ModelRequest(
            model_key=model_key,
            stage=stage,
            payload=dict(self.payload),
            input_tokens=self.input_tokens,
            max_new_tokens=self.max_new_tokens,
            visual_pixels=self.visual_pixels,
            batch_size=self.batch_size,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
        )
        request.validate()
        return request

    def validate(self) -> None:
        model_key = ModelKey(self.model_key)
        if self.input_tokens < 0:
            raise RequestValidationError("input_tokens must be >= 0")
        if self.input_tokens > MAX_INPUT_TOKENS:
            raise RequestValidationError(
                f"input_tokens exceeds limit {MAX_INPUT_TOKENS}"
            )
        if not 1 <= self.max_new_tokens <= MAX_OUTPUT_TOKENS:
            raise RequestValidationError(
                f"max_new_tokens must be between 1 and {MAX_OUTPUT_TOKENS}"
            )
        if self.input_tokens + self.max_new_tokens > MAX_TOTAL_TOKENS:
            raise RequestValidationError(
                f"total token budget exceeds limit {MAX_TOTAL_TOKENS}"
            )
        if self.visual_pixels is not None:
            if self.visual_pixels < 1:
                raise RequestValidationError("visual_pixels must be positive")
            if self.visual_pixels > MAX_VISION_PIXELS:
                raise RequestValidationError(
                    f"visual_pixels exceeds limit {MAX_VISION_PIXELS}"
                )
        if self.batch_size < 1:
            raise RequestValidationError("batch_size must be >= 1")
        if model_key == ModelKey.KOLORS and self.batch_size != 1:
            raise RequestValidationError(
                "Kolors requests must use batch_size=1 under the single-GPU scheduler"
            )
        if self.timeout_seconds <= 0:
            raise RequestValidationError("timeout_seconds must be positive")


@dataclass(frozen=True)
class CommandPlan:
    request_id: str
    model_key: ModelKey
    stage: TaskStage
    conda_env: str
    model_path_env: str
    model_path: str
    argv: tuple[str, ...]
    timeout_seconds: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["model_key"] = self.model_key.value
        data["stage"] = self.stage.value
        data["argv"] = list(self.argv)
        return data


@dataclass(frozen=True)
class RuntimeResult:
    request_id: str
    status: str
    plan: CommandPlan
    started_at: float
    finished_at: float
    output: Mapping[str, Any] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        return self.finished_at - self.started_at


@dataclass(frozen=True)
class UnloadReport:
    status: str
    plans: tuple[CommandPlan, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "plans": [plan.to_dict() for plan in self.plans],
            "note": self.note,
        }


class Runner(Protocol):
    def run(
        self,
        plan: CommandPlan,
        *,
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        ...

    def cancel(self, request_id: str) -> None:
        ...


class DevRunner:
    """A deterministic runner used by dev-mode scheduling tests.

    It never imports CUDA libraries and never loads a model. Optional per-stage
    delays allow tests to prove the GPU lease is held globally.
    """

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        delay_by_request_id: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.delay_by_request_id = dict(delay_by_request_id or {})
        self.calls: list[CommandPlan] = []
        self.started_request_ids: list[str] = []
        self.finished_request_ids: list[str] = []
        self.cancelled_request_ids: set[str] = set()
        self._lock = threading.Lock()

    def run(
        self,
        plan: CommandPlan,
        *,
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        with self._lock:
            self.calls.append(plan)
            self.started_request_ids.append(plan.request_id)

        deadline = time.monotonic() + self.delay_by_request_id.get(
            plan.request_id, self.delay_seconds
        )
        while time.monotonic() < deadline:
            if cancel_event.is_set():
                with self._lock:
                    self.cancelled_request_ids.add(plan.request_id)
                raise TimeoutError(f"request cancelled: {plan.request_id}")
            time.sleep(min(0.01, max(deadline - time.monotonic(), 0)))

        if cancel_event.is_set():
            with self._lock:
                self.cancelled_request_ids.add(plan.request_id)
            raise TimeoutError(f"request cancelled: {plan.request_id}")

        with self._lock:
            self.finished_request_ids.append(plan.request_id)
        return {
            "run_mode": "dev",
            "planned_command": list(plan.argv),
            "model_key": plan.model_key.value,
            "stage": plan.stage.value,
        }

    def cancel(self, request_id: str) -> None:
        with self._lock:
            self.cancelled_request_ids.add(request_id)


@dataclass
class _ActiveLease:
    request_id: str
    model_key: ModelKey
    stage: TaskStage
    acquired_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model_key": self.model_key.value,
            "stage": self.stage.value,
            "acquired_at": self.acquired_at,
        }


class ModelManager:
    _global_gpu_lock = threading.Lock()

    def __init__(
        self,
        *,
        runner: Optional[Runner] = None,
        environ: Optional[Mapping[str, str]] = None,
        specs: Mapping[ModelKey, ModelSpec] = MODEL_SPECS,
    ) -> None:
        self._runner = runner or DevRunner()
        self._environ = environ if environ is not None else os.environ
        self._specs = dict(specs)
        self._state_lock = threading.RLock()
        self._active: Optional[_ActiveLease] = None
        self._cancel_events: MutableMapping[str, threading.Event] = {}
        self._history: list[dict[str, Any]] = []

    @staticmethod
    def model_for_stage(
        stage: Union[TaskStage, str],
        *,
        deepseek_failed: bool = False,
    ) -> ModelKey:
        normalized_stage = TaskStage(stage)
        if normalized_stage == TaskStage.IMAGE_GENERATION:
            return ModelKey.KOLORS
        if normalized_stage == TaskStage.VISION_REVIEW:
            return ModelKey.QWEN_VL
        if normalized_stage == TaskStage.LOCAL_REVIEW_D2:
            # D2 is a local safety/review retry. If DeepSeek fails upstream, we
            # intentionally call the local Qwen AWQ runtime again instead of
            # skipping or reusing a stale external-provider answer.
            return ModelKey.QWEN14B_AWQ
        if normalized_stage == TaskStage.TEXT_ANALYSIS:
            return ModelKey.QWEN14B_AWQ
        if normalized_stage == TaskStage.UNLOAD:
            raise ModelRuntimeError("UNLOAD is not routed from task stages")
        raise ModelRuntimeError(f"unsupported task stage: {stage}")

    def request_for_stage(
        self,
        stage: Union[TaskStage, str],
        *,
        deepseek_failed: bool = False,
        **kwargs: Any,
    ) -> ModelRequest:
        return ModelRequest(
            model_key=self.model_for_stage(stage, deepseek_failed=deepseek_failed),
            stage=stage,
            **kwargs,
        ).normalized()

    def plan(self, request: ModelRequest) -> CommandPlan:
        normalized = request.normalized()
        spec = self._specs[ModelKey(normalized.model_key)]
        model_path = self._environ.get(spec.path_env)
        if not model_path:
            raise ModelRuntimeError(
                f"missing model path environment variable: {spec.path_env}"
            )

        conda_executable = self._environ.get("CONDA_EXE", "conda")
        conda_env = self._environ.get(
            spec.conda_env_variable,
            spec.conda_env,
        )
        argv = (
            conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            conda_env,
            "python",
            "-m",
            "backend.model_runtime.worker",
            "--model-key",
            spec.key.value,
            "--model-path",
            model_path,
            "--stage",
            TaskStage(normalized.stage).value,
            "--request-id",
            normalized.request_id,
        )
        return CommandPlan(
            request_id=normalized.request_id,
            model_key=spec.key,
            stage=TaskStage(normalized.stage),
            conda_env=conda_env,
            model_path_env=spec.path_env,
            model_path=model_path,
            argv=argv,
            timeout_seconds=normalized.timeout_seconds,
        )

    def run(
        self,
        request: ModelRequest,
        *,
        lease_timeout_seconds: Optional[float] = None,
    ) -> RuntimeResult:
        plan = self.plan(request)
        lease_timeout = (
            plan.timeout_seconds if lease_timeout_seconds is None else lease_timeout_seconds
        )
        acquired = self._global_gpu_lock.acquire(timeout=lease_timeout)
        if not acquired:
            raise TimeoutError("timed out waiting for the global GPU lease")

        cancel_event = threading.Event()
        started_at = time.monotonic()
        with self._state_lock:
            self._active = _ActiveLease(
                request_id=plan.request_id,
                model_key=plan.model_key,
                stage=plan.stage,
                acquired_at=started_at,
            )
            self._cancel_events[plan.request_id] = cancel_event
            self._history.append(
                {
                    "request_id": plan.request_id,
                    "event": "started",
                    "model_key": plan.model_key.value,
                    "stage": plan.stage.value,
                    "time": started_at,
                }
            )

        try:
            output = self._run_with_timeout(plan, cancel_event)
            status = "completed"
            return RuntimeResult(
                request_id=plan.request_id,
                status=status,
                plan=plan,
                started_at=started_at,
                finished_at=time.monotonic(),
                output=output,
            )
        except TimeoutError:
            self.cancel(plan.request_id)
            raise
        finally:
            finished_at = time.monotonic()
            with self._state_lock:
                self._history.append(
                    {
                        "request_id": plan.request_id,
                        "event": "finished",
                        "model_key": plan.model_key.value,
                        "stage": plan.stage.value,
                        "time": finished_at,
                    }
                )
                self._active = None
                self._cancel_events.pop(plan.request_id, None)
            self._global_gpu_lock.release()

    def _run_with_timeout(
        self,
        plan: CommandPlan,
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        result_box: dict[str, Mapping[str, Any]] = {}
        error_box: dict[str, BaseException] = {}

        def target() -> None:
            try:
                result_box["result"] = self._runner.run(
                    plan,
                    cancel_event=cancel_event,
                )
            except BaseException as exc:  # pragma: no cover - defensive join path
                error_box["error"] = exc

        thread = threading.Thread(
            target=target,
            name=f"dev-model-runtime-{plan.request_id[:8]}",
            daemon=True,
        )
        thread.start()
        thread.join(plan.timeout_seconds)
        if thread.is_alive():
            cancel_event.set()
            self._runner.cancel(plan.request_id)
            raise TimeoutError(f"model stage timed out: {plan.request_id}")
        if "error" in error_box:
            raise error_box["error"]
        return result_box.get("result", {})

    def cancel(self, request_id: str) -> bool:
        with self._state_lock:
            event = self._cancel_events.get(request_id)
            if event is None:
                return False
            event.set()
        self._runner.cancel(request_id)
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "single_gpu_mutex": True,
                "active": self._active.to_dict() if self._active else None,
                "known_models": {
                    spec.key.value: {
                        "conda_env": self._environ.get(
                            spec.conda_env_variable,
                            spec.conda_env,
                        ),
                        "conda_env_variable": spec.conda_env_variable,
                        "path_env": spec.path_env,
                        "path_configured": bool(self._environ.get(spec.path_env)),
                    }
                    for spec in self._specs.values()
                },
                "history": list(self._history),
            }

    def unload_report(
        self, model_key: Optional[Union[ModelKey, str]] = None
    ) -> UnloadReport:
        keys = (
            [ModelKey(model_key)]
            if model_key is not None
            else [
                ModelKey.QWEN14B_AWQ,
                ModelKey.KOLORS,
                ModelKey.QWEN_VL,
            ]
        )
        plans = tuple(
            self.plan(
                ModelRequest(
                    model_key=key,
                    stage=TaskStage.UNLOAD,
                    timeout_seconds=10,
                )
            )
            for key in keys
        )
        return UnloadReport(
            status="planned",
            plans=plans,
            note=(
                "Models are isolated in Conda subprocesses; unload is reported "
                "as planned subprocess commands."
            ),
        )
