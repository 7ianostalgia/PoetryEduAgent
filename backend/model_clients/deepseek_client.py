from __future__ import annotations

import json
import os
from typing import Any, Mapping, Protocol

import httpx

from backend.utils import validate_json_schema

from .qwen_awq_worker import _extract_json


class DeepSeekReviewError(RuntimeError):
    """Signals that the workflow must enter LOCAL_REVIEW_D2."""


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any],
        timeout: float,
    ) -> Any: ...


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (
            base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        ).rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.http_client = http_client or httpx.Client()

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def review(
        self,
        *,
        review_input: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        timeout_seconds: float = 90,
    ) -> dict[str, Any]:
        if not self.configured:
            raise DeepSeekReviewError(
                "DEEPSEEK_API_KEY 尚未配置，工作流应进入 LOCAL_REVIEW_D2"
            )
        schema = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
        payload = json.dumps(review_input, ensure_ascii=False, separators=(",", ":"))
        try:
            response = self.http_client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是古诗文文字教学资源的核心审核裁判。只审核作者、"
                                "朝代、原文、释义、意象、情感、讲解、课堂问题、"
                                "测评题和 rubric；不要审核图片或视觉构图。"
                                "只输出符合 JSON Schema 的 JSON 对象，不要输出 Markdown。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"审核输入：\n{payload}\n\nJSON Schema：\n{schema}",
                        },
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            result = _extract_json(str(content))
            validate_json_schema(result, output_schema)
        except Exception as exc:
            raise DeepSeekReviewError(
                f"DeepSeek 审核失败，工作流应进入 LOCAL_REVIEW_D2：{exc}"
            ) from exc

        result.setdefault("reviewer", self.model)
        result["fallback_used"] = False
        return result
