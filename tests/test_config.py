from pathlib import Path

import pytest

from backend.config import Settings, load_settings
from backend.main import create_app


def test_run_mode_accepts_only_dev_or_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUN_MODE", "dev")
    assert load_settings().run_mode == "dev"

    monkeypatch.setenv("RUN_MODE", "gpu")
    assert load_settings().run_mode == "gpu"

    monkeypatch.setenv("RUN_MODE", "legacy")
    with pytest.raises(ValueError, match="dev.*gpu"):
        load_settings()


def test_create_app_selects_gpu_service(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            run_mode="gpu",
            frontend_static_dir=tmp_path / "frontend",
            database_path=tmp_path / "knowledge.db",
            runtime_database_path=tmp_path / "runtime.db",
            output_dir=tmp_path / "outputs",
        )
    )

    assert app.state.learning_service.run_mode == "gpu"
    assert app.state.settings.port == 7860
