#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.model_clients import QwenVisionClient, QwenVisionRequest


VISION_SCHEMA = {
    "type": "object",
    "required": [
        "image_summary",
        "person_count",
        "key_elements_detected",
        "missing_elements",
        "possible_errors",
    ],
    "properties": {
        "image_summary": {"type": "string"},
        "person_count": {"type": "integer"},
        "key_elements_detected": {
            "type": "object",
            "required": [
                "one_poet",
                "moon",
                "moonlight_on_ground",
                "ancient_bed",
                "modern_objects",
                "snow_or_real_frost",
            ],
            "additionalProperties": False,
            "properties": {
                "one_poet": {"type": "boolean"},
                "moon": {"type": "boolean"},
                "moonlight_on_ground": {"type": "boolean"},
                "ancient_bed": {"type": "boolean"},
                "modern_objects": {"type": "boolean"},
                "snow_or_real_frost": {"type": "boolean"},
            },
        },
        "missing_elements": {"type": "array", "items": {"type": "string"}},
        "possible_errors": {"type": "array", "items": {"type": "string"}},
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行一次 Qwen-VL 图像描述烟雾测试")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    result = QwenVisionClient().review(
        QwenVisionRequest(
            task_name="smoke_vision_review",
            image_path=args.image,
            prompt=(
                "观察这张《静夜思》教学意象图。客观描述人物数量、明月、"
                "床榻、地面月光、现代物品，并指出与“床前明月光，疑是地上霜”"
                "不够一致的地方。不要根据提示词猜测，只报告画面中实际看见的内容。"
            ),
            output_schema=VISION_SCHEMA,
            max_new_tokens=384,
        )
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
