#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.generation import KolorsClient, KolorsRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="运行一张 gpu Kolors 生图烟雾测试")
    parser.add_argument("--model", default=None)
    parser.add_argument("--output-dir", default="smoke/kolors")
    parser.add_argument("--seed", type=int, default=20260620)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--size", type=int, default=768, choices=(512, 768, 1024))
    args = parser.parse_args()

    client = KolorsClient(model_path=args.model)
    result = client.generate(
        KolorsRequest(
            prompt=(
                "古代中国夜晚室内，一名唐代诗人坐在低矮木榻旁，"
                "窗外明月清晰可见，冷白月光铺在床前青砖地面上如霜，"
                "安静、清冷、思乡，国风写实课堂插画"
            ),
            negative_prompt=(
                "现代家具，电灯，暖黄色灯光，多个人物，现代建筑，"
                "文字，水印，卡通，畸形，模糊"
            ),
            output_dir=args.output_dir,
            seed=args.seed,
            width=args.size,
            height=args.size,
            steps=args.steps,
        )
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
