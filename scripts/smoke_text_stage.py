#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents import TextStageRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 gpu Qwen 文本阶段烟雾测试")
    parser.add_argument("--db", default="data/poetry_edu.db")
    parser.add_argument(
        "--output",
        default=str(
            Path(os.getenv("OUTPUT_DIR", "outputs")) / "smoke" / "text_stage.json"
        ),
    )
    args = parser.parse_args()
    result = TextStageRunner(db_path=args.db).run(
        poem="床前明月光，疑是地上霜。举头望明月，低头思故乡。",
        student_profile={
            "grade": "七年级",
            "level": "basic",
            "weakness": ["imagery_analysis", "emotion_summary"],
            "goal": "understand_poetic_meaning_and_emotion",
            "preferences": {"needs_visual_support": True},
        },
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), **result["model_metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
