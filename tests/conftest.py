from __future__ import annotations

import importlib
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "data" / "examples"

# Tests always exercise the deterministic dev application, even when the
# developer's local .env is configured for gpu mode.
os.environ["RUN_MODE"] = "dev"
os.environ["DEV_STAGE_DELAY_SECONDS"] = "0"


@pytest.fixture(scope="session")
def app():
    try:
        module = importlib.import_module("backend.main")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "找不到 backend.main；dev 应用入口必须为 backend.main:app。"
        )

    application = getattr(module, "app", None)
    if application is None:
        pytest.fail("backend.main 未导出 app。")
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def job_payload() -> dict[str, str]:
    return {"poem_id": "jing-ye-si"}


@pytest.fixture()
def created_job(client: TestClient, job_payload: dict[str, str]) -> dict[str, Any]:
    response = client.post("/api/learning/jobs", json=job_payload)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body.get("job_id")
    return body


def wait_until_terminal(
    client: TestClient,
    job_id: str,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}

    while time.monotonic() < deadline:
        response = client.get(f"/api/learning/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("stage") in {"completed", "failed"}:
            return last
        time.sleep(0.01)

    pytest.fail(f"dev 任务未在 {timeout} 秒内结束，最后状态：{last}")
