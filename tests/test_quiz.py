from fastapi.testclient import TestClient

from .conftest import wait_until_terminal


CORRECT_ANSWERS = {
    "answers": [
        {"question_id": "objective-1", "answer": "A"},
        {"question_id": "objective-2", "answer": "D"},
        {
            "question_id": "subjective-1",
            "answer": "月光照在地上，洁白得像一层白霜。",
        },
        {
            "question_id": "subjective-2",
            "answer": "诗人先抬头望明月，再低头思念故乡，表达思乡。",
        },
    ]
}


def test_completed_job_accepts_and_grades_quiz(
    client: TestClient,
    created_job: dict,
) -> None:
    job_id = created_job["job_id"]
    terminal = wait_until_terminal(client, job_id)
    assert terminal["stage"] == "completed", terminal

    response = client.post(
        f"/api/learning/jobs/{job_id}/quiz",
        json=CORRECT_ANSWERS,
    )
    assert response.status_code == 200
    report = response.json()

    assert report["job_id"] == job_id
    assert report["poem_id"] == "jing-ye-si"
    assert report["score"] == report["max_score"] == 100
    assert report["objective_correct"] == report["objective_total"] == 2
    assert report["subjective_completed"] == report["subjective_total"] == 2
    assert report["passed"] is True
    assert len(report["details"]) == 4
    assert all(item["feedback"].strip() for item in report["details"])


def test_quiz_requires_exactly_four_answers(client: TestClient) -> None:
    response = client.post(
        "/api/learning/jobs/not-a-real-job/quiz",
        json={"answers": [{"question_id": "objective-1", "answer": "A"}]},
    )
    assert response.status_code == 422
    assert "detail" in response.json()


def test_unknown_job_quiz_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/learning/jobs/not-a-real-job/quiz",
        json=CORRECT_ANSWERS,
    )
    assert response.status_code == 404
    assert "detail" in response.json()
