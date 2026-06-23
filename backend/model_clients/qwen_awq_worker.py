from __future__ import annotations

import gc
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from backend.utils import SchemaValidationError, validate_json_schema


def _repair_common_json_string_errors(text: str) -> str:
    """Repair common local-model quote mistakes without changing structure."""
    repaired: list[str] = []
    in_string = False
    escaped = False
    length = len(text)

    for index, char in enumerate(text):
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            repaired.append(char)
            escaped = False
            continue
        if char == "\\":
            repaired.append(char)
            escaped = True
            continue
        if char == '"':
            next_index = index + 1
            while next_index < length and text[next_index].isspace():
                next_index += 1
            next_char = text[next_index] if next_index < length else ""
            if next_char and next_char not in ",:}]":
                repaired.append('\\"')
                continue
            repaired.append(char)
            in_string = False
            continue
        if char in "]}":
            next_index = index + 1
            while next_index < length and text[next_index].isspace():
                next_index += 1
            next_char = text[next_index] if next_index < length else ""
            if not next_char or next_char in ",}]":
                repaired.append('"')
                in_string = False
        repaired.append(char)

    return "".join(repaired)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
        if not isinstance(value, dict):
            raise ValueError("模型输出必须是 JSON 对象")
        return value
    except json.JSONDecodeError:
        # Local models occasionally place a literal newline or tab inside a
        # JSON string. JSONDecoder(strict=False) safely accepts those control
        # characters; schema validation still checks the resulting structure.
        try:
            value = json.loads(stripped, strict=False)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        try:
            value = json.loads(
                _repair_common_json_string_errors(stripped),
                strict=False,
            )
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder(strict=False)
        for index, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise ValueError("模型输出无法解析为 JSON 对象")


def _gpu_stats(torch: Any) -> dict[str, float]:
    if not torch.cuda.is_available():
        return {}
    return {
        "allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
        "reserved_mb": round(torch.cuda.memory_reserved() / 1024**2, 1),
    }


def _append_json_correction(
    messages: list[dict[str, str]],
    *,
    raw_text: str,
    error: Exception,
) -> None:
    messages.append({"role": "assistant", "content": raw_text})
    messages.append(
        {
            "role": "user",
            "content": (
                "上一次输出不是合法 JSON 或未通过 JSON Schema 校验："
                + str(error)
                + "。请修正 JSON 语法、字段、类型和数组数量，"
                "只重新输出完整 JSON 对象，不要输出 Markdown。"
            ),
        }
    )


def main() -> int:
    envelope = json.loads(sys.stdin.read())
    payloads = envelope.get("requests") if isinstance(envelope, dict) else None
    is_batch = payloads is not None
    if payloads is None:
        payloads = [envelope]
    if not isinstance(payloads, list) or not payloads:
        raise ValueError("requests 必须是非空数组")
    model_path = Path(os.environ["LOCAL_LLM_MODEL"]).expanduser().resolve()
    config_path = model_path / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Qwen AWQ config 不存在：{config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    quantization = config.get("quantization_config") or {}
    if quantization.get("quant_method") != "awq":
        raise RuntimeError("拒绝加载非 AWQ 模型")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    before = _gpu_stats(torch)
    model = None
    tokenizer = None
    inputs = None
    generated = None
    load_started = time.monotonic()
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            device_map="cuda",
            torch_dtype="auto",
            local_files_only=True,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )
        model.eval()
        torch.cuda.synchronize()
        load_seconds = time.monotonic() - load_started

        results = []
        for payload in payloads:
            torch.manual_seed(int(payload["seed"]))
            schema_text = json.dumps(
                payload["output_schema"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        str(payload["system_prompt"]).strip()
                        + "\n只输出一个符合给定 JSON Schema 的 JSON 对象，不要输出 Markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        str(payload["user_prompt"]).strip()
                        + "\n\nJSON Schema：\n"
                        + schema_text
                    ),
                },
            ]
            generate_started = time.monotonic()
            attempts = 0
            while True:
                attempts += 1
                prompt = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                inputs = tokenizer(
                    prompt,
                    return_tensors="pt",
                    truncation=True,
                    max_length=int(payload["max_input_tokens"]),
                ).to(model.device)
                with torch.inference_mode():
                    generated = model.generate(
                        **inputs,
                        max_new_tokens=int(payload["max_new_tokens"]),
                        do_sample=float(payload["temperature"]) > 0,
                        temperature=max(float(payload["temperature"]), 0.01),
                        top_p=float(payload["top_p"]),
                        pad_token_id=tokenizer.eos_token_id,
                    )
                torch.cuda.synchronize()
                new_tokens = generated[0, inputs["input_ids"].shape[1] :]
                raw_text = tokenizer.decode(
                    new_tokens,
                    skip_special_tokens=True,
                ).strip()
                try:
                    output = _extract_json(raw_text)
                    validate_json_schema(output, payload["output_schema"])
                    break
                except (SchemaValidationError, ValueError) as exc:
                    if attempts >= 2:
                        raise
                    _append_json_correction(
                        messages,
                        raw_text=raw_text,
                        error=exc,
                    )
                    del generated
                    generated = None
                    del inputs
                    inputs = None
            torch.cuda.synchronize()
            generate_seconds = time.monotonic() - generate_started
            metrics = {
                "model": "Qwen2.5-14B-Instruct-AWQ",
                "model_path": str(model_path),
                "quant_method": "awq",
                "input_tokens": int(inputs["input_ids"].shape[1]),
                "output_tokens": int(new_tokens.shape[0]),
                "schema_attempts": attempts,
                "load_seconds": round(load_seconds, 3),
                "generate_seconds": round(generate_seconds, 3),
                "gpu_before": before,
                "gpu_peak_allocated_mb": round(
                    torch.cuda.max_memory_allocated() / 1024**2, 1
                ),
                "gpu_peak_reserved_mb": round(
                    torch.cuda.max_memory_reserved() / 1024**2, 1
                ),
            }
            results.append(
                {
                    "task_name": payload["task_name"],
                    "output": output,
                    "raw_text": raw_text,
                    "metrics": metrics,
                }
            )
            del generated
            generated = None
            del inputs
            inputs = None
        result = {"results": results}
    finally:
        del generated
        del inputs
        del model
        del tokenizer
        gc.collect()
        if "torch" in locals() and torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

    after = _gpu_stats(torch)
    for item in result["results"]:
        item["metrics"]["gpu_after_release"] = after
    response = result if is_batch else result["results"][0]
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
