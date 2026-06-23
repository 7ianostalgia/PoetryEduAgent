from __future__ import annotations

import threading
import time

import pytest

from backend.model_runtime import (
    ModelKey,
    ModelManager,
    ModelRequest,
    DevRunner,
    RequestValidationError,
    TaskStage,
)


ENVIRON = {
    "LOCAL_LLM_MODEL": "/models/qwen14b-awq",
    "KOLORS_MODEL": "/models/kolors",
    "VISION_MODEL": "/models/qwen-vl",
}


def test_model_command_plans_use_fixed_conda_envs_and_env_paths() -> None:
    manager = ModelManager(environ=ENVIRON)

    qwen = manager.plan(
        ModelRequest(
            model_key=ModelKey.QWEN14B_AWQ,
            stage=TaskStage.TEXT_ANALYSIS,
            request_id="req-qwen",
        )
    )
    kolors = manager.plan(
        ModelRequest(
            model_key=ModelKey.KOLORS,
            stage=TaskStage.IMAGE_GENERATION,
            visual_pixels=512 * 512,
            request_id="req-kolors",
        )
    )
    qwen_vl = manager.plan(
        ModelRequest(
            model_key=ModelKey.QWEN_VL,
            stage=TaskStage.VISION_REVIEW,
            visual_pixels=640 * 480,
            request_id="req-vl",
        )
    )

    assert qwen.conda_env == "poetryedu-qwen14b-awq"
    assert kolors.conda_env == "poetryedu-kolors"
    assert qwen_vl.conda_env == "poetryedu-qwen-vl"
    assert qwen.model_path == "/models/qwen14b-awq"
    assert kolors.model_path == "/models/kolors"
    assert qwen_vl.model_path == "/models/qwen-vl"

    assert qwen.argv[:5] == (
        "conda",
        "run",
        "--no-capture-output",
        "-n",
        "poetryedu-qwen14b-awq",
    )
    assert "backend.model_runtime.worker" in qwen.argv
    assert ("--model-key", "qwen14b_awq") == (
        qwen.argv[qwen.argv.index("--model-key")],
        qwen.argv[qwen.argv.index("--model-key") + 1],
    )
    assert ("--model-path", "/models/kolors") == (
        kolors.argv[kolors.argv.index("--model-path")],
        kolors.argv[kolors.argv.index("--model-path") + 1],
    )
    assert ("--stage", "VISION_REVIEW") == (
        qwen_vl.argv[qwen_vl.argv.index("--stage")],
        qwen_vl.argv[qwen_vl.argv.index("--stage") + 1],
    )


def test_model_command_plan_honors_configured_conda_names() -> None:
    manager = ModelManager(
        environ={
            **ENVIRON,
            "CONDA_EXE": "/opt/conda/bin/conda",
            "QWEN_CONDA_ENV": "custom-qwen",
        }
    )

    plan = manager.plan(
        ModelRequest(
            model_key=ModelKey.QWEN14B_AWQ,
            stage=TaskStage.TEXT_ANALYSIS,
        )
    )

    assert plan.conda_env == "custom-qwen"
    assert plan.argv[:5] == (
        "/opt/conda/bin/conda",
        "run",
        "--no-capture-output",
        "-n",
        "custom-qwen",
    )


def test_kolors_rejects_batch_size_larger_than_one() -> None:
    manager = ModelManager(environ=ENVIRON)

    with pytest.raises(RequestValidationError, match="batch_size=1"):
        manager.plan(
            ModelRequest(
                model_key=ModelKey.KOLORS,
                stage=TaskStage.IMAGE_GENERATION,
                visual_pixels=512 * 512,
                batch_size=2,
            )
        )


def test_concurrent_stages_do_not_hold_gpu_lease_at_same_time() -> None:
    first_request_id = "first-qwen"
    second_request_id = "second-kolors"
    runner = DevRunner(delay_by_request_id={first_request_id: 0.12})
    manager = ModelManager(runner=runner, environ=ENVIRON)
    snapshots: list[dict] = []

    first = ModelRequest(
        model_key=ModelKey.QWEN14B_AWQ,
        stage=TaskStage.TEXT_ANALYSIS,
        request_id=first_request_id,
        timeout_seconds=1,
    )
    second = ModelRequest(
        model_key=ModelKey.KOLORS,
        stage=TaskStage.IMAGE_GENERATION,
        visual_pixels=256 * 256,
        request_id=second_request_id,
        timeout_seconds=1,
    )

    first_thread = threading.Thread(target=lambda: manager.run(first))
    first_thread.start()

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        snapshot = manager.snapshot()
        snapshots.append(snapshot)
        if snapshot["active"] and snapshot["active"]["request_id"] == first_request_id:
            break
        time.sleep(0.005)
    else:
        pytest.fail("first request did not acquire the GPU lease")

    second_result: list[str] = []
    second_thread = threading.Thread(
        target=lambda: second_result.append(manager.run(second).request_id)
    )
    second_thread.start()

    time.sleep(0.03)
    active_while_second_waits = manager.snapshot()["active"]
    assert active_while_second_waits["request_id"] == first_request_id
    assert second_result == []

    first_thread.join(timeout=1)
    second_thread.join(timeout=1)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_result == [second_request_id]
    assert runner.started_request_ids == [first_request_id, second_request_id]

    history = [
        (event["request_id"], event["event"]) for event in manager.snapshot()["history"]
    ]
    assert history.index((first_request_id, "finished")) < history.index(
        (second_request_id, "started")
    )


def test_local_review_d2_after_deepseek_failure_routes_to_qwen_awq() -> None:
    manager = ModelManager(environ=ENVIRON)

    request = manager.request_for_stage(
        TaskStage.LOCAL_REVIEW_D2,
        deepseek_failed=True,
        request_id="d2-retry",
    )
    plan = manager.plan(request)

    assert request.model_key == ModelKey.QWEN14B_AWQ
    assert plan.conda_env == "poetryedu-qwen14b-awq"
    assert ("--stage", "LOCAL_REVIEW_D2") == (
        plan.argv[plan.argv.index("--stage")],
        plan.argv[plan.argv.index("--stage") + 1],
    )


def test_snapshot_cancel_timeout_and_unload_report_interfaces() -> None:
    runner = DevRunner(delay_seconds=0.1)
    manager = ModelManager(runner=runner, environ=ENVIRON)
    request = ModelRequest(
        model_key=ModelKey.QWEN14B_AWQ,
        stage=TaskStage.TEXT_ANALYSIS,
        request_id="timeout-qwen",
        timeout_seconds=0.02,
    )

    with pytest.raises(TimeoutError):
        manager.run(request)

    snapshot = manager.snapshot()
    assert snapshot["single_gpu_mutex"] is True
    assert snapshot["active"] is None

    unload = manager.unload_report(ModelKey.KOLORS)
    assert unload.status == "planned"
    assert unload.plans[0].conda_env == "poetryedu-kolors"
    assert unload.plans[0].stage == TaskStage.UNLOAD
