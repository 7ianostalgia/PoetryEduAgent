from fastapi.testclient import TestClient

from .conftest import wait_until_terminal


def test_successful_job_has_structured_result(
    client: TestClient,
    created_job: dict,
) -> None:
    job_id = created_job["job_id"]
    terminal = wait_until_terminal(client, job_id)
    assert terminal["stage"] == "completed", terminal
    assert terminal["progress"] == 100

    response = client.get(f"/api/learning/jobs/{job_id}/result")
    assert response.status_code == 200
    result = response.json()

    assert result["job_id"] == job_id
    poem = result["poem"]
    assert poem["poem_id"] == "jing-ye-si"
    assert poem["title"] == "静夜思"
    assert poem["author"] == "李白"
    assert poem["translation"].strip()
    assert poem["appreciation"].strip()
    assert len(poem["text"]) == len(poem["pinyin"]) == 4
    assert poem["knowledge_points"]
    assert poem["learning_steps"]
    assert len(result["quiz"]) == 4


def test_unknown_job_result_returns_404(client: TestClient) -> None:
    response = client.get("/api/learning/jobs/not-a-real-job/result")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_frontend_section_endpoints_are_available(
    client: TestClient,
    created_job: dict,
) -> None:
    job_id = created_job["job_id"]
    wait_until_terminal(client, job_id)

    overview = client.get(f"/api/learning/jobs/{job_id}/overview")
    assert overview.status_code == 200
    assert overview.json()["ready"] is True

    for section in ("rag", "text", "image-result", "reviews", "quiz", "agents"):
        response = client.get(f"/api/learning/jobs/{job_id}/{section}")
        assert response.status_code == 200, (section, response.text)
        assert response.json()["job_id"] == job_id
        if section == "image-result":
            assert "prompt_snapshot" in response.json()
        if section == "agents":
            agents = response.json()["agents"]
            assert len(agents) == 8
            assert {agent["id"] for agent in agents} >= {
                "poem_analysis",
                "text_resources",
                "vision_reviewer",
                "final_gate",
            }

    report = client.get(f"/api/learning/jobs/{job_id}/report")
    assert report.status_code == 409
