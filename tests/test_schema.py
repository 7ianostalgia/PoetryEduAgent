from fastapi.testclient import TestClient


REQUIRED_OPERATIONS = {
    "/api/health": "get",
    "/api/config": "get",
    "/api/learning/jobs": "post",
    "/api/learning/jobs/{job_id}": "get",
    "/api/learning/jobs/{job_id}/result": "get",
    "/api/learning/jobs/{job_id}/quiz": "post",
}


def test_openapi_contains_runtime_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]

    for path, method in REQUIRED_OPERATIONS.items():
        assert path in paths, f"OpenAPI 缺少 {path}"
        assert method in paths[path], f"OpenAPI 缺少 {method.upper()} {path}"

    components = schema.get("components", {}).get("schemas", {})
    assert components, "API 必须使用结构化请求/响应 Schema"


def test_create_job_declares_json_request_schema(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/learning/jobs"
    ]["post"]
    json_body = operation["requestBody"]["content"]["application/json"]
    assert "schema" in json_body


def test_result_and_quiz_declare_success_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operations = (
        ("/api/learning/jobs/{job_id}/result", "get"),
        ("/api/learning/jobs/{job_id}/quiz", "post"),
    )
    for path, method in operations:
        response_200 = schema["paths"][path][method]["responses"]["200"]
        json_response = response_200["content"]["application/json"]
        assert "schema" in json_response
