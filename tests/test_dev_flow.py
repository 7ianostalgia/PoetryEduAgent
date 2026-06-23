from fastapi.testclient import TestClient

from .conftest import wait_until_terminal


def test_dev_learning_flow(
    client: TestClient,
    job_payload: dict[str, str],
) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["run_mode"] == "dev"

    create = client.post("/api/learning/jobs", json=job_payload)
    assert create.status_code == 202
    job_id = create.json()["job_id"]

    terminal = wait_until_terminal(client, job_id)
    assert terminal["stage"] == "completed", terminal

    result = client.get(f"/api/learning/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["job_id"] == job_id

    answers = []
    for question in result.json()["quiz"]:
        answer = (
            question["options"][0]["label"]
            if question["kind"] == "objective"
            else "完成主观题作答"
        )
        answers.append(
            {"question_id": question["question_id"], "answer": answer}
        )
    quiz = client.post(
        f"/api/learning/jobs/{job_id}/quiz",
        json={"answers": answers},
    )
    assert quiz.status_code == 200
    assert quiz.json()["job_id"] == job_id


def test_dev_flow_keeps_request_identity(
    client: TestClient,
    job_payload: dict[str, str],
) -> None:
    create = client.post("/api/learning/jobs", json=job_payload)
    job_id = create.json()["job_id"]
    terminal = wait_until_terminal(client, job_id)
    assert terminal["stage"] == "completed", terminal

    result = client.get(f"/api/learning/jobs/{job_id}/result").json()
    assert result["poem"]["poem_id"] == job_payload["poem_id"]
    assert result["poem"]["title"] == "静夜思"
