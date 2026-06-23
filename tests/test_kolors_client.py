from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.generation import KolorsClient, KolorsRequest
from backend.generation.kolors_client import KolorsValidationError


class FakeRunner:
    def __init__(self) -> None:
        self.argv: list[str] = []
        self.payload: dict = {}
        self.env: dict = {}

    def run(self, argv, *, input, env, timeout):
        self.argv = argv
        self.payload = json.loads(input)
        self.env = dict(env)
        result = {
            "image_path": f"{self.payload['output_dir']}/kolors_seed_7.png",
            "metadata_path": f"{self.payload['output_dir']}/kolors_seed_7.json",
            "seed": 7,
            "metrics": {"mode": "fake"},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")


def test_client_uses_clear_conda_environment_and_safe_output(tmp_path: Path):
    runner = FakeRunner()
    client = KolorsClient(
        conda_executable="conda",
        conda_env="poetryedu-kolors",
        output_root=tmp_path,
        model_path="/models/kolors",
        runner=runner,
    )
    result = client.generate(
        KolorsRequest(
            prompt="月夜",
            negative_prompt="现代物品",
            output_dir="job-1",
            seed=7,
            width=768,
            height=768,
        )
    )

    assert runner.argv[:5] == [
        "conda",
        "run",
        "--no-capture-output",
        "-n",
        "poetryedu-kolors",
    ]
    assert runner.env["KOLORS_MODEL"] == "/models/kolors"
    assert Path(runner.payload["output_dir"]).parent == tmp_path
    assert result.seed == 7


def test_kolors_rejects_batch_generation(tmp_path: Path):
    request = KolorsRequest(
        prompt="月夜",
        negative_prompt="",
        output_dir="job-1",
        batch_size=2,
    )
    with pytest.raises(KolorsValidationError, match="batch_size=1"):
        request.validate(tmp_path)


def test_kolors_rejects_output_path_escape(tmp_path: Path):
    request = KolorsRequest(
        prompt="月夜",
        negative_prompt="",
        output_dir=str(tmp_path.parent / "outside"),
    )
    with pytest.raises(KolorsValidationError, match="OUTPUT_DIR"):
        request.validate(tmp_path)
