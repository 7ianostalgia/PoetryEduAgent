from __future__ import annotations

import time
from types import SimpleNamespace

from backend.models import (
    CreateLearningJobRequest,
    LearningJob,
    LearningStage,
    QuizAnswer,
    QuizSubmission,
    utc_now,
)
from backend.orchestration.gpu_workflow import WorkflowEvent
from backend.orchestration.gpu_service import GpuLearningService
from backend.storage import InMemoryLearningRepository


class FakeWorkflow:
    def run(self, *, poem, student_profile, job_id, on_event):
        on_event(
            WorkflowEvent(
                "text_stage",
                "正在生成文本资源",
                "poem_analysis",
                {"emotion": "思乡"},
            )
        )
        on_event(WorkflowEvent("completed", "底层工作流已完成"))
        return {
            "job_id": job_id,
            "poem": poem,
            "student_profile": student_profile,
            "text_stage": {
                "agent_outputs": {
                    "quiz": {
                        "objective_questions": [
                            {
                                "id": "obj_1",
                                "answer": "A",
                                "explanation": "解释一",
                            },
                            {
                                "id": "obj_2",
                                "answer": "B",
                                "explanation": "解释二",
                            },
                        ],
                        "subjective_questions": [
                            {"id": "sub_1", "rubric": "评分点一"},
                            {"id": "sub_2", "rubric": "评分点二"},
                        ],
                    }
                }
            },
        }


class BrokenWorkflow:
    def run(self, **kwargs):
        raise RuntimeError(
            "traceback details\n模型输出无法解析为 JSON 对象\nmore details"
        )


class FakeQwenClient:
    def run_text(self, request):
        return SimpleNamespace(
            output={
                "subjective_scores": [
                    {"question_id": "sub_1", "score": 4, "feedback": "基本准确"},
                    {"question_id": "sub_2", "score": 5, "feedback": "表达清楚"},
                ],
                "weak_points": ["意象作用还可展开"],
                "diagnosis": "基础理解正确。",
                "next_learning_path": ["复习意象", "补写情感依据"],
            }
        )


def wait_for_terminal(service, job_id):
    for _ in range(100):
        job = service.get_job(job_id)
        if job.stage in {LearningStage.COMPLETED, LearningStage.FAILED}:
            return job
        time.sleep(0.01)
    raise AssertionError("gpu service did not reach a terminal state")


def test_gpu_service_saves_result_before_marking_completed():
    repository = InMemoryLearningRepository()
    service = GpuLearningService(
        repository,
        FakeWorkflow(),
        qwen_client=FakeQwenClient(),
    )

    job = service.create_job(CreateLearningJobRequest())
    completed = wait_for_terminal(service, job.job_id)

    assert completed.stage == LearningStage.COMPLETED
    assert completed.progress == 100
    assert service.get_result(job.job_id)["job_id"] == job.job_id
    events = service.get_events(job.job_id)
    assert events[1]["agent_id"] == "poem_analysis"
    assert events[1]["output"] == {"emotion": "思乡"}


def test_gpu_service_grades_objective_and_subjective_answers():
    repository = InMemoryLearningRepository()
    service = GpuLearningService(
        repository,
        FakeWorkflow(),
        qwen_client=FakeQwenClient(),
    )
    job = service.create_job(CreateLearningJobRequest())
    wait_for_terminal(service, job.job_id)

    report = service.submit_quiz(
        job.job_id,
        QuizSubmission(
            answers=[
                QuizAnswer(question_id="obj_1", answer="A"),
                QuizAnswer(question_id="obj_2", answer="C"),
                QuizAnswer(question_id="sub_1", answer="月光营造清冷氛围。"),
                QuizAnswer(question_id="sub_2", answer="动作变化引出思乡。"),
            ]
        ),
    )

    assert report["objective_score"] == 1
    assert report["objective_total"] == 2
    assert report["subjective_scores"][1]["score"] == 5
    assert report["subjective_score"] == 9
    assert report["max_score"] == 12
    assert report["score"] == 83


def test_gpu_service_hides_worker_traceback_from_public_job_error():
    service = GpuLearningService(
        InMemoryLearningRepository(),
        BrokenWorkflow(),
        qwen_client=FakeQwenClient(),
    )
    job = service.create_job(CreateLearningJobRequest())
    failed = wait_for_terminal(service, job.job_id)

    assert failed.stage == LearningStage.FAILED
    assert failed.error == "视觉模型多次未返回合法 JSON，请重新生成"
    assert "traceback" not in failed.error


def test_gpu_service_progress_does_not_regress_during_re_review():
    repository = InMemoryLearningRepository()
    service = GpuLearningService(
        repository,
        FakeWorkflow(),
        qwen_client=FakeQwenClient(),
    )
    now = utc_now()
    repository.create_job(
        LearningJob(
            job_id="job_progress",
            poem_id="jing-ye-si",
            stage=LearningStage.IMAGE_CORRECTION,
            progress=90,
            message="重绘",
            created_at=now,
            updated_at=now,
        )
    )

    service._update(
        "job_progress",
        WorkflowEvent("local_review_d2", "复审"),
    )

    assert service.get_job("job_progress").progress == 90
