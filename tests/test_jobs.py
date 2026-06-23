from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from .conftest import wait_until_terminal


ALLOWED_STAGES = {
    "queued",
    "analyzing",
    "generating_resources",
    "generating_quiz",
    "completed",
    "failed",
}


def test_create_and_read_job(
    client: TestClient,
    job_payload: dict[str, str],
) -> None:
    created_response = client.post("/api/learning/jobs", json=job_payload)

    assert created_response.status_code == 202
    created = created_response.json()
    assert created["job_id"]
    assert created["poem_id"] == "jing-ye-si"
    assert created["stage"] in ALLOWED_STAGES
    assert 0 <= created["progress"] <= 100
    assert created["message"]
    datetime.fromisoformat(created["created_at"].replace("Z", "+00:00"))

    read_response = client.get(f"/api/learning/jobs/{created['job_id']}")
    assert read_response.status_code == 200
    current = read_response.json()
    assert current["job_id"] == created["job_id"]
    assert current["stage"] in ALLOWED_STAGES
    assert 0 <= current["progress"] <= 100
    assert "error" in current
    datetime.fromisoformat(current["created_at"].replace("Z", "+00:00"))
    datetime.fromisoformat(current["updated_at"].replace("Z", "+00:00"))


def test_create_job_rejects_unknown_poem(client: TestClient) -> None:
    response = client.post(
        "/api/learning/jobs",
        json={"poem_id": "unknown-poem"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()


def test_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get("/api/learning/jobs/not-a-real-job")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_job_history_supports_role_limit_and_offset(
    client: TestClient,
) -> None:
    teacher = client.post(
        "/api/learning/jobs",
        json={"poem_id": "jing-ye-si", "role": "teacher"},
    ).json()
    client.post(
        "/api/learning/jobs",
        json={"poem_id": "jing-ye-si", "role": "student"},
    )
    response = client.get(
        "/api/learning/jobs",
        params={"role": "teacher", "limit": 1, "offset": 0},
    )
    assert response.status_code == 200
    assert [item["job_id"] for item in response.json()] == [teacher["job_id"]]


def test_incremental_events_api_returns_ids(
    client: TestClient, created_job: dict
) -> None:
    job_id = created_job["job_id"]
    first = client.get(
        f"/api/learning/jobs/{job_id}/events",
        params={"limit": 1},
    ).json()
    assert first["events"][0]["id"] >= 1
    second = client.get(
        f"/api/learning/jobs/{job_id}/events",
        params={"after_id": first["next_after_id"]},
    ).json()
    assert all(
        event["id"] > first["next_after_id"] for event in second["events"]
    )


def test_sse_resumes_after_last_event_id(
    client: TestClient, created_job: dict
) -> None:
    job_id = created_job["job_id"]
    wait_until_terminal(client, job_id)
    events = client.get(f"/api/learning/jobs/{job_id}/events").json()["events"]
    response = client.get(
        f"/api/learning/jobs/{job_id}/events/stream",
        headers={"Last-Event-ID": str(events[0]["id"])},
    )
    assert response.status_code == 200
    assert f"id: {events[0]['id']}\n" not in response.text
    assert f"id: {events[1]['id']}\n" in response.text
