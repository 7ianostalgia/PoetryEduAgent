from fastapi.testclient import TestClient


def test_health_reports_run_mode(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["run_mode"] == "dev"
    assert body["service"] == "PoetryEduAgent"


def test_config_reports_runtime_addresses(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["run_mode"] == "dev"
    assert body["port"] == 7860
    assert body["frontend"] == "http://localhost:7860"
    assert body["api_docs"] == "http://localhost:7860/docs"
