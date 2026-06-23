from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.model_clients import QwenVisionClient, QwenVisionRequest
from backend.model_clients.qwen_awq_worker import (
    _extract_json,
    _repair_common_json_string_errors,
)
from backend.model_clients.qwen_vl_client import QwenVisionRequestError
from backend.model_clients.qwen_vl_worker import (
    _append_json_correction,
    _normalize_vision_field_aliases,
    _schema_example,
)


SCHEMA = {
    "type": "object",
    "required": ["person_count"],
    "properties": {"person_count": {"type": "integer"}},
}


class FakeRunner:
    def __init__(self) -> None:
        self.argv = []
        self.env = {}
        self.payload = {}

    def run(self, argv, *, input, env, timeout):
        self.argv = argv
        self.env = dict(env)
        self.payload = json.loads(input)
        result = {
            "task_name": self.payload["task_name"],
            "output": {"person_count": 1},
            "raw_text": '{"person_count":1}',
            "metrics": {"mode": "fake"},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")


def test_qwen_vl_uses_clear_environment_and_safe_image(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"not-a-real-image")
    runner = FakeRunner()
    client = QwenVisionClient(
        conda_executable="conda",
        conda_env="poetryedu-qwen-vl",
        output_root=tmp_path,
        model_path="/models/qwen-vl",
        runner=runner,
    )
    result = client.review(
        QwenVisionRequest(
            task_name="vision_review",
            image_path=str(image),
            prompt="描述图片",
            output_schema=SCHEMA,
        )
    )
    assert runner.argv[4] == "poetryedu-qwen-vl"
    assert runner.env["VISION_MODEL"] == "/models/qwen-vl"
    assert result.output["person_count"] == 1


def test_qwen_vl_text_mode_does_not_require_schema(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"not-a-real-image")
    payload = QwenVisionRequest(
        task_name="vision_observation",
        image_path=str(image),
        prompt="只描述实际画面",
        response_mode="text",
        max_new_tokens=256,
    ).to_payload(tmp_path)

    assert payload["response_mode"] == "text"
    assert payload["output_schema"] is None
    assert payload["max_new_tokens"] == 256


def test_qwen_vl_rejects_images_outside_output_root(tmp_path: Path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"x")
    request = QwenVisionRequest(
        task_name="vision_review",
        image_path=str(outside),
        prompt="描述图片",
        output_schema=SCHEMA,
    )
    with pytest.raises(QwenVisionRequestError, match="OUTPUT_DIR"):
        request.to_payload(tmp_path)


def test_qwen_vl_rejects_excessive_visual_pixels(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"x")
    request = QwenVisionRequest(
        task_name="vision_review",
        image_path=str(image),
        prompt="描述图片",
        output_schema=SCHEMA,
        max_pixels=4096 * 4096,
    )
    with pytest.raises(QwenVisionRequestError, match="安全上限"):
        request.to_payload(tmp_path)


def test_qwen_vl_retry_includes_previous_invalid_output():
    messages = [{"role": "user", "content": [{"type": "text", "text": "描述"}]}]
    _append_json_correction(
        messages,
        raw_text='{"person_count": "一"}',
        error=ValueError("person_count 应为整数"),
        attempt=1,
    )

    assert messages[-2]["role"] == "assistant"
    assert messages[-2]["content"][0]["text"] == '{"person_count": "一"}'
    assert "单行" in messages[-1]["content"][0]["text"]


def test_qwen_vl_uses_compact_output_example_instead_of_schema():
    example = _schema_example(
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "count": {"type": "integer"},
                "detected": {
                    "type": "object",
                    "properties": {"moon": {"type": "boolean"}},
                },
                "issues": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }
    )
    assert example == {
        "summary": "",
        "count": 0,
        "detected": {"moon": False},
        "issues": [],
    }


def test_json_repair_handles_unescaped_quote_and_missing_closing_quote():
    raw = '{"possible_errors":["灯笼"不符合月光主导场景]}'
    assert _extract_json(raw) == {
        "possible_errors": ['灯笼"不符合月光主导场景']
    }


def test_json_repair_does_not_change_valid_json():
    raw = '{"possible_errors":["灯笼不符合月光主导场景"]}'
    assert _repair_common_json_string_errors(raw) == raw


def test_qwen_vl_normalizes_known_ancient_bed_alias():
    assert _normalize_vision_field_aliases(
        {"key_elements_detected": {"ancientnt_bed": False}}
    ) == {"key_elements_detected": {"ancient_bed": False}}
