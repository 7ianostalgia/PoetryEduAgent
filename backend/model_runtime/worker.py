"""Stable subprocess entrypoint for model-runtime command plans.

The gpu model clients use dedicated workers. This generic worker keeps
ModelManager command planning and dev-mode scheduling tests deterministic
without importing CUDA libraries.
"""

from __future__ import annotations

import argparse
import json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PoetryEduAgent model worker")
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--request-id", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(
        json.dumps(
            {
                "status": "planned-only",
                "model_key": args.model_key,
                "model_path": args.model_path,
                "stage": args.stage,
                "request_id": args.request_id,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
