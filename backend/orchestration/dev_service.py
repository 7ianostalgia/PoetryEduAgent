from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Thread
from typing import Optional
from uuid import uuid4

from backend.dev import build_learning_result, grade_quiz
from backend.models import (
    CreateLearningJobRequest,
    LearningJob,
    LearningResult,
    LearningStage,
    QuizReport,
    QuizSubmission,
    utc_now,
)
from backend.storage import InMemoryLearningRepository


@dataclass(frozen=True)
class StageUpdate:
    stage: LearningStage
    progress: int
    message: str


DEV_PIPELINE = (
    StageUpdate(LearningStage.ANALYZING, 25, "正在分析诗歌内容"),
    StageUpdate(LearningStage.GENERATING_RESOURCES, 55, "正在生成学习资源"),
    StageUpdate(LearningStage.GENERATING_QUIZ, 80, "正在生成小测"),
)


class DevLearningService:
    run_mode = "dev"

    def __init__(
        self,
        repository: InMemoryLearningRepository,
        *,
        stage_delay_seconds: float,
    ) -> None:
        self._repository = repository
        self._stage_delay_seconds = max(stage_delay_seconds, 0)

    def create_job(
        self,
        request: str | CreateLearningJobRequest,
    ) -> LearningJob:
        poem_id = request if isinstance(request, str) else request.poem_id
        role = "student" if isinstance(request, str) else request.role
        now = utc_now()
        job = LearningJob(
            job_id=uuid4().hex,
            poem_id=poem_id,
            role=role,
            stage=LearningStage.QUEUED,
            progress=0,
            message="任务已创建",
            created_at=now,
            updated_at=now,
        )
        self._repository.create_job(job)
        self._repository.append_event(
            job.job_id,
            {
                "stage": "queued",
                "agent_id": "poem_analysis",
                "status": "waiting",
                "message": job.message,
                "output": None,
                "created_at": now.isoformat(),
            },
        )
        Thread(
            target=self._run_dev_pipeline,
            args=(job.job_id,),
            name=f"dev-learning-{job.job_id[:8]}",
            daemon=True,
        ).start()
        return job

    def get_job(self, job_id: str) -> Optional[LearningJob]:
        return self._repository.get_job(job_id)

    def get_result(self, job_id: str) -> Optional[LearningResult]:
        return self._repository.get_result(job_id)

    def get_report(self, job_id: str):
        return self._repository.get_report(job_id)

    def list_jobs(
        self, *, role: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[LearningJob]:
        return self._repository.list_jobs(role=role, limit=limit, offset=offset)

    def get_events(
        self, job_id: str, *, after_id: int = 0, limit: int = 200
    ) -> list[dict]:
        return self._repository.get_events(
            job_id, after_id=after_id, limit=limit
        )

    def submit_quiz(
        self, job_id: str, submission: QuizSubmission
    ) -> QuizReport:
        report = grade_quiz(job_id, submission)
        answers = {
            item.question_id: item.answer for item in submission.answers
        }
        saved = self._repository.save_report(report)
        self._repository.save_quiz_answers(job_id, answers)
        return saved

    def _set_stage(self, job_id: str, update: StageUpdate) -> None:
        def apply(job: LearningJob) -> LearningJob:
            return job.model_copy(
                update={
                    "stage": update.stage,
                    "progress": update.progress,
                    "message": update.message,
                    "updated_at": utc_now(),
                    "error": None,
                }
            )

        self._repository.update_job(job_id, apply)
        event_specs = {
            LearningStage.ANALYZING: [("poem_analysis", "running")],
            LearningStage.GENERATING_RESOURCES: [
                ("poem_analysis", "completed"),
                ("text_resources", "running"),
            ],
            LearningStage.GENERATING_QUIZ: [("text_resources", "running")],
            LearningStage.COMPLETED: [
                ("text_resources", "completed"),
                ("final_gate", "completed"),
            ],
        }.get(update.stage, [])
        for agent_id, event_status in event_specs:
            self._repository.append_event(
                job_id,
                {
                    "stage": update.stage.value,
                    "agent_id": agent_id,
                    "status": event_status,
                    "message": update.message,
                    "output": None,
                    "created_at": utc_now().isoformat(),
                },
            )

    def _fail_job(self, job_id: str, error: Exception) -> None:
        def apply(job: LearningJob) -> LearningJob:
            return job.model_copy(
                update={
                    "stage": LearningStage.FAILED,
                    "message": "dev 任务执行失败",
                    "updated_at": utc_now(),
                    "error": str(error),
                }
            )

        self._repository.update_job(job_id, apply)

    def _run_dev_pipeline(self, job_id: str) -> None:
        try:
            for update in DEV_PIPELINE:
                if self._stage_delay_seconds:
                    time.sleep(self._stage_delay_seconds)
                self._set_stage(job_id, update)

            result = build_learning_result(job_id)
            self._repository.save_result(result)
            self._set_stage(
                job_id,
                StageUpdate(LearningStage.COMPLETED, 100, "学习资源已生成"),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            self._fail_job(job_id, exc)
