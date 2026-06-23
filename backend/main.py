from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api import public_router, router
from backend.config import Settings, settings
from backend.orchestration import DevLearningService
from backend.orchestration.gpu_service import GpuLearningService
from backend.orchestration.gpu_workflow import GpuLearningWorkflow
from backend.storage import InMemoryLearningRepository, SqliteLearningRepository


def create_app(app_settings: Settings = settings) -> FastAPI:
    app = FastAPI(
        title="PoetryEduAgent API",
        version="0.3.0",
        description="古诗学习的 dev 无卡演示与 gpu 模式 API。",
    )
    if app_settings.run_mode == "dev":
        repository = InMemoryLearningRepository()
        app.state.learning_service = DevLearningService(
            repository,
            stage_delay_seconds=app_settings.dev_stage_delay_seconds,
        )
    else:
        repository = SqliteLearningRepository(
            app_settings.runtime_database_path
        )
        app.state.learning_service = GpuLearningService(
            repository,
            GpuLearningWorkflow(
                db_path=str(app_settings.database_path),
                output_root=str(app_settings.output_dir),
            ),
        )
    app.state.settings = app_settings
    app.include_router(router)
    app.include_router(public_router)

    app.mount(
        "/",
        StaticFiles(
            directory=app_settings.frontend_static_dir,
            html=True,
            check_dir=False,
        ),
        name="frontend",
    )
    return app


app = create_app()
