from __future__ import annotations

import pytest

from backend.model_clients import DeepSeekClient, DeepSeekReviewError


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"pass":true,"review_result":"pass"}'
                    }
                }
            ]
        }


class FakeHttpClient:
    def __init__(self):
        self.url = ""
        self.payload = {}

    def post(self, url, *, headers, json, timeout):
        self.url = url
        self.payload = json
        assert headers["Authorization"] == "Bearer test-key"
        return FakeResponse()


def test_deepseek_uses_configured_flash_model():
    http = FakeHttpClient()
    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://example.invalid",
        model="deepseek-v4-flash",
        http_client=http,
    )
    result = client.review(
        review_input={"poem": "静夜思"},
        output_schema={"type": "object"},
    )
    assert http.url == "https://example.invalid/chat/completions"
    assert http.payload["model"] == "deepseek-v4-flash"
    assert "不要审核图片" in http.payload["messages"][0]["content"]
    assert result["pass"] is True
    assert result["fallback_used"] is False


def test_missing_key_requests_local_review_fallback():
    client = DeepSeekClient(api_key="")
    with pytest.raises(DeepSeekReviewError, match="LOCAL_REVIEW_D2"):
        client.review(
            review_input={"poem": "静夜思"},
            output_schema={"type": "object"},
        )
