from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _gpu_stats(torch: Any) -> dict[str, float]:
    if not torch.cuda.is_available():
        return {}
    return {
        "allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
        "reserved_mb": round(torch.cuda.memory_reserved() / 1024**2, 1),
    }


def _safe_output_dir(raw: str, output_root: str) -> Path:
    root = Path(output_root).expanduser().resolve()
    target = Path(raw).expanduser().resolve()
    if target != root and root not in target.parents:
        raise ValueError("output_dir 必须位于 OUTPUT_DIR 内")
    target.mkdir(parents=True, exist_ok=True)
    return target


def main() -> int:
    payload = json.loads(sys.stdin.read())
    if int(payload.get("batch_size", 1)) != 1:
        raise ValueError("Kolors worker 只允许 batch_size=1")

    model_path = Path(os.environ["KOLORS_MODEL"]).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"Kolors 模型不存在：{model_path}")
    output_dir = _safe_output_dir(
        str(payload["output_dir"]),
        os.environ["OUTPUT_DIR"],
    )

    import torch
    from diffusers import KolorsPipeline

    pipe = None
    image = None
    before = _gpu_stats(torch)
    load_started = time.monotonic()
    try:
        torch.cuda.reset_peak_memory_stats()
        pipe = KolorsPipeline.from_pretrained(
            str(model_path),
            torch_dtype=torch.float16,
            variant="fp16",
        ).to("cuda")
        torch.cuda.synchronize()
        load_seconds = time.monotonic() - load_started

        seed = int(payload["seed"])
        generate_started = time.monotonic()
        with torch.inference_mode():
            image = pipe(
                prompt=str(payload["prompt"]),
                negative_prompt=str(payload.get("negative_prompt") or ""),
                num_inference_steps=int(payload["steps"]),
                guidance_scale=float(payload["guidance_scale"]),
                width=int(payload["width"]),
                height=int(payload["height"]),
                generator=torch.Generator(device="cuda").manual_seed(seed),
            ).images[0]
        torch.cuda.synchronize()
        generate_seconds = time.monotonic() - generate_started

        image_path = output_dir / f"kolors_seed_{seed}.png"
        metadata_path = output_dir / f"kolors_seed_{seed}.json"
        image.save(image_path)
        metrics = {
            "model": "Kolors",
            "model_path": str(model_path),
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
        metadata = {
            **payload,
            "image_path": str(image_path),
            "metrics": metrics,
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result = {
            "image_path": str(image_path),
            "metadata_path": str(metadata_path),
            "seed": seed,
            "metrics": metrics,
        }
    finally:
        del image
        del pipe
        gc.collect()
        if "torch" in locals() and torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

    result["metrics"]["gpu_after_release"] = _gpu_stats(torch)
    Path(result["metadata_path"]).write_text(
        json.dumps(
            {
                **payload,
                "image_path": result["image_path"],
                "metrics": result["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
