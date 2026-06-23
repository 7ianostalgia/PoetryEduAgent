#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.orchestration.gpu_workflow import GpuLearningWorkflow, WorkflowEvent


def main() -> int:
    workflow = GpuLearningWorkflow(
        db_path=os.getenv("POETRY_DB_PATH", "data/poetry_edu.db"),
        output_root=os.getenv("OUTPUT_DIR", "outputs"),
    )

    def report(event: WorkflowEvent) -> None:
        print(f"[{event.stage}] {event.message}", flush=True)

    result = workflow.run(
        poem="床前明月光，疑是地上霜。举头望明月，低头思故乡。",
        student_profile={
            "grade": "七年级",
            "level": "basic",
            "weakness": ["imagery_analysis", "emotion_summary"],
            "goal": "understand_poetic_meaning_and_emotion",
            "preferences": {"needs_visual_support": True},
        },
        job_id="gpu_jingyesi_case",
        on_event=report,
    )
    print(
        json.dumps(
            {
                "job_id": result["job_id"],
                "result_path": result["result_path"],
                "image_path": result["image"]["image_path"],
                "vision_review": result["vision_review"]["output"],
                "final_review": result["final_review"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
