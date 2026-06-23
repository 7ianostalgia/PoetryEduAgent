from __future__ import annotations

import json
import subprocess

import pytest

from backend.model_clients import QwenAwqClient, QwenTextRequest
from backend.model_clients.qwen_awq_worker import (
    _append_json_correction,
    _extract_json,
)
from backend.model_clients.qwen_awq_client import QwenRequestError


SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}


def test_json_extractor_accepts_literal_control_characters():
    result = _extract_json('{"summary":"第一行\n第二行","items":[]}')
    assert result["summary"] == "第一行\n第二行"


def test_invalid_json_retry_requests_complete_json_object():
    messages = [{"role": "user", "content": "生成 JSON"}]
    _append_json_correction(
        messages,
        raw_text='{"scene":"月夜",}',
        error=ValueError("JSON 语法错误"),
    )
    assert messages[-2]["role"] == "assistant"
    assert "完整 JSON 对象" in messages[-1]["content"]


class FakeRunner:
    def __init__(self) -> None:
        self.argv = []
        self.env = {}
        self.payload = {}

    def run(self, argv, *, input, env, timeout):
        self.argv = argv
        self.env = dict(env)
        self.payload = json.loads(input)
        payloads = self.payload.get("requests", [self.payload])
        items = [
            {
                "task_name": item["task_name"],
                "output": {"summary": "测试完成"},
                "raw_text": '{"summary":"测试完成"}',
                "metrics": {"mode": "fake"},
            }
            for item in payloads
        ]
        result = items[0] if "requests" not in self.payload else {"results": items}
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")


def test_qwen_client_uses_awq_environment_and_model_path():
    runner = FakeRunner()
    client = QwenAwqClient(
        conda_executable="conda",
        conda_env="poetryedu-qwen14b-awq",
        model_path="/models/qwen-awq",
        runner=runner,
    )
    result = client.run_text(
        QwenTextRequest(
            task_name="diagnosis",
            system_prompt="你是教学助手。",
            user_prompt="分析学情。",
            output_schema=SCHEMA,
        )
    )

    assert runner.argv[4] == "poetryedu-qwen14b-awq"
    assert runner.env["LOCAL_LLM_MODEL"] == "/models/qwen-awq"
    assert result.output["summary"] == "测试完成"


def test_qwen_request_rejects_unbounded_tokens():
    request = QwenTextRequest(
        task_name="diagnosis",
        system_prompt="教学助手",
        user_prompt="分析",
        output_schema=SCHEMA,
        max_input_tokens=100_000,
    )
    with pytest.raises(QwenRequestError, match="8192"):
        request.validate()


def test_qwen_batch_uses_one_worker_for_multiple_agents():
    runner = FakeRunner()
    client = QwenAwqClient(
        conda_executable="conda",
        conda_env="poetryedu-qwen14b-awq",
        model_path="/models/qwen-awq",
        runner=runner,
    )
    requests = [
        QwenTextRequest(
            task_name=name,
            system_prompt="教学助手",
            user_prompt="分析",
            output_schema=SCHEMA,
        )
        for name in ("diagnosis", "analysis", "resources")
    ]
    results = client.run_batch(requests)
    assert [item.task_name for item in results] == [
        "diagnosis",
        "analysis",
        "resources",
    ]
    assert len(runner.payload["requests"]) == 3


def test_json_extractor_accepts_fenced_or_prefixed_json():
    assert _extract_json('```json\n{"summary":"好"}\n```') == {"summary": "好"}
    assert _extract_json('说明：{"summary":"好"}') == {"summary": "好"}
