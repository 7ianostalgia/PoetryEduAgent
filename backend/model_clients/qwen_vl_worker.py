from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from backend.utils import SchemaValidationError, validate_json_schema

from .qwen_awq_worker import _extract_json


VISION_FIELD_ALIASES = {
    "ancence_bed": "ancient_bed",
    "ancientnt_bed": "ancient_bed",
}


def _normalize_vision_field_aliases(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_vision_field_aliases(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, item in value.items():
        normalized_key = VISION_FIELD_ALIASES.get(key, key)
        normalized[normalized_key] = _normalize_vision_field_aliases(item)
    return normalized


def _gpu_stats(torch: Any) -> dict[str, float]:
    if not torch.cuda.is_available():
        return {}
    return {
        "allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
        "reserved_mb": round(torch.cuda.memory_reserved() / 1024**2, 1),
    }


def _append_json_correction(
    messages: list[dict[str, Any]],
    *,
    raw_text: str,
    error: Exception,
    attempt: int,
) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": raw_text}],
        }
    )
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"第 {attempt} 次输出不是合法 JSON 或未通过 Schema："
                        f"{error}。请直接修正你刚才的输出，只返回单行、完整、"
                        "可由标准 JSON 解析器读取的对象。必须严格使用 Schema "
                        "字段名；字符串中的换行写成空格，不要输出 Markdown。"
                    ),
                }
            ],
        }
    )


def _schema_example(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties") or {}
        return {
            key: _schema_example(value)
            for key, value in properties.items()
        }
    if schema_type == "array":
        return []
    if schema_type == "boolean":
        return False
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    return ""


def main() -> int:
    payload = json.loads(sys.stdin.read())
    model_path = Path(os.environ["VISION_MODEL"]).expanduser().resolve()
    if not (model_path / "config.json").exists():
        raise FileNotFoundError(f"Qwen-VL 模型不存在：{model_path}")

    import torch
    from qwen_vl_utils import process_vision_info
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    before = _gpu_stats(torch)
    model = None
    processor = None
    inputs = None
    generated_ids = None
    load_started = time.monotonic()
    try:
        processor = AutoProcessor.from_pretrained(
            str(model_path),
            min_pixels=int(payload["min_pixels"]),
            max_pixels=int(payload["max_pixels"]),
            local_files_only=True,
        )
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            str(model_path),
            torch_dtype=torch.bfloat16,
            device_map="cuda",
            local_files_only=True,
            low_cpu_mem_usage=True,
        )
        model.eval()
        torch.cuda.synchronize()
        load_seconds = time.monotonic() - load_started

        response_mode = str(payload.get("response_mode") or "json")
        output_example = (
            json.dumps(
                _schema_example(dict(payload["output_schema"])),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if response_mode == "json"
            else ""
        )
        if response_mode == "text":
            output_instruction = (
                "\n只输出一段中文，不要 JSON、Markdown、换行或解释。"
                "严格按模板填写并用中文分号分隔："
                "人物数量=数字；单一古代诗人=是/否；明月=有/无；"
                "床前地面月光=有/无；古代床榻=有/无；现代物品=有/无；"
                "真实冰霜或雪=有/无；人工照明=有/无；"
                "画面概述=不超过50字；问题=无或逗号分隔；"
                "修改建议=无或逗号分隔。每个判断字段只能选择并写出一个词，"
                "禁止照抄“是/否”或“有/无”。总长度不超过220个汉字。"
            )
        else:
            output_instruction = (
                "\n只输出一个 JSON 对象，不要输出 Markdown，不要解释字段，"
                "不要复述 Schema。字段名和数据类型必须严格遵循下面的短样板，"
                "请用实际观察结果替换样板值：\n"
                + output_example
            )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": payload["image_path"]},
                    {
                        "type": "text",
                        "text": (
                            str(payload["prompt"]).strip()
                            + output_instruction
                        ),
                    },
                ],
            }
        ]
        text = processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(model.device)

        generate_started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            with torch.inference_mode():
                generated_ids = model.generate(
                    **inputs,
                    max_new_tokens=int(payload["max_new_tokens"]),
                    do_sample=False,
                )
            torch.cuda.synchronize()
            trimmed = [
                output[len(input_ids) :]
                for input_ids, output in zip(inputs.input_ids, generated_ids)
            ]
            raw_text = processor.batch_decode(
                trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0].strip()
            if response_mode == "text":
                output = {"observation_text": " ".join(raw_text.split())}
                break
            try:
                output = _normalize_vision_field_aliases(
                    _extract_json(raw_text)
                )
                validate_json_schema(output, payload["output_schema"])
                break
            except (SchemaValidationError, ValueError) as exc:
                if attempts >= 3:
                    raise ValueError(
                        "视觉模型连续三次未返回合法 JSON；最后输出："
                        + repr(raw_text[:1200])
                    ) from exc
                _append_json_correction(
                    messages,
                    raw_text=raw_text,
                    error=exc,
                    attempt=attempts,
                )
                messages[-1]["content"][0]["text"] += (
                    "\n必须严格按照这个短样板返回："
                    + output_example
                )
                text = processor.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                inputs = processor(
                    text=[text],
                    images=image_inputs,
                    videos=video_inputs,
                    padding=True,
                    return_tensors="pt",
                ).to(model.device)
                del generated_ids
                generated_ids = None
        generate_seconds = time.monotonic() - generate_started
        metrics = {
            "model": "Qwen2.5-VL-7B-Instruct",
            "model_path": str(model_path),
            "load_seconds": round(load_seconds, 3),
            "generate_seconds": round(generate_seconds, 3),
            "visual_pixels_limit": int(payload["max_pixels"]),
            "output_tokens": int(trimmed[0].shape[0]),
            "schema_attempts": attempts,
            "gpu_before": before,
            "gpu_peak_allocated_mb": round(
                torch.cuda.max_memory_allocated() / 1024**2, 1
            ),
            "gpu_peak_reserved_mb": round(
                torch.cuda.max_memory_reserved() / 1024**2, 1
            ),
        }
        result = {
            "task_name": payload["task_name"],
            "output": output,
            "raw_text": raw_text,
            "metrics": metrics,
        }
    finally:
        del generated_ids
        del inputs
        del model
        del processor
        gc.collect()
        if "torch" in locals() and torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

    result["metrics"]["gpu_after_release"] = _gpu_stats(torch)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
