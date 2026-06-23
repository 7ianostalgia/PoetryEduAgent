from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

from backend.models import LearningJob, LearningStage, utc_now
from backend.orchestration.gpu_workflow import WorkflowEvent
from backend.orchestration.gpu_service import GpuLearningService
from backend.storage import InMemoryLearningRepository


class UnusedWorkflow:
    deepseek_client = SimpleNamespace(configured=True)

    def run(self, **kwargs):
        raise AssertionError("workflow should not run")

    @staticmethod
    def _text_review_input(**kwargs):
        return kwargs

    @staticmethod
    def _run_text_review(*, review_input, emit):
        emit(
            WorkflowEvent(
                "deepseek_review",
                "复审完成",
                "text_reviewer",
                status="running",
            )
        )
        return {
            "pass": True,
            "fallback_used": False,
            "knowledge_issues": [],
            "quiz_issues": [],
            "teaching_issues": [],
            "required_actions": [],
        }


class FeedbackQwen:
    def __init__(self):
        self.request = None

    def run_text(self, request):
        self.request = request
        return SimpleNamespace(output={"updated_module": "三分钟月夜联想导入"})


def _teacher_service():
    repository = InMemoryLearningRepository()
    qwen = FeedbackQwen()
    service = GpuLearningService(repository, UnusedWorkflow(), qwen_client=qwen)
    now = utc_now()
    job = LearningJob(
        job_id="job_teacher",
        poem_id="jing-ye-si",
        role="teacher",
        stage=LearningStage.COMPLETED,
        progress=100,
        message="完成",
        created_at=now,
        updated_at=now,
    )
    repository.create_job(job)
    repository.save_result(
        {
            "job_id": job.job_id,
            "poem": "床前明月光",
            "text_stage": {
                "agent_outputs": {
                    "learning_resources": {
                        "classroom_intro": "旧导入",
                        "layered_explanations": {"basic": "基础"},
                        "guided_questions": ["问题一"],
                    },
                    "quiz": {"objective_questions": [], "subjective_questions": []},
                }
            },
            "final_decision": {
                "pass": True,
                "text_pass": True,
                "vision_pass": True,
                "failed_parts": [],
            },
        }
    )
    return service, repository, qwen


def test_feedback_sends_structured_evidence_and_only_updates_target():
    service, _, qwen = _teacher_service()
    before = service.get_result("job_teacher")

    response = service.apply_feedback(
        "job_teacher",
        target_module="classroom_intro",
        feedback="压缩到三分钟，并加入月夜联想。",
    )

    agent_input = json.loads(qwen.request.user_prompt)
    assert agent_input == {
        "target_module": "classroom_intro",
        "previous_output": "旧导入",
        "teacher_feedback": "压缩到三分钟，并加入月夜联想。",
        "poem": "床前明月光",
        "student_profile": {},
        "preserve_instruction": "只修改 target_module，其他所有模块保持原样",
    }
    after = service.get_result("job_teacher")
    assert after["text_stage"]["agent_outputs"]["learning_resources"][
        "classroom_intro"
    ] == "三分钟月夜联想导入"
    assert after["text_stage"]["agent_outputs"]["learning_resources"][
        "layered_explanations"
    ] == before["text_stage"]["agent_outputs"]["learning_resources"][
        "layered_explanations"
    ]
    assert response["agent_input"]["teacher_feedback_included_verbatim"] is True
    reviewer_events = [
        event
        for event in service.get_events("job_teacher")
        if event.get("agent_id") == "text_reviewer"
    ]
    assert reviewer_events[-1]["status"] == "completed"


def test_old_results_receive_new_resource_defaults():
    service, _, _ = _teacher_service()
    resources = service.get_result("job_teacher")["text_stage"]["agent_outputs"][
        "learning_resources"
    ]
    assert resources["teaching_goals"] == []
    assert resources["teaching_key_difficulties"] == {
        "key_points": [],
        "difficulties": [],
    }
    assert resources["classroom_activities"] == []


def test_teacher_package_excludes_prompts_and_raw_reviews():
    service, _, _ = _teacher_service()
    package = service.build_teacher_package("job_teacher")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert set(archive.namelist()) == {
            "教师资源包.md",
            "resources.json",
            "quiz.json",
            "review_summary.json",
        }
        combined = b"\n".join(archive.read(name) for name in archive.namelist())
    assert b"standard_prompt_json" not in combined
    assert b"prompt_snapshot" not in combined
    assert b"vision_review" not in combined


def test_agent_events_are_incremental_and_status_driven():
    service, repository, _ = _teacher_service()
    service._record_event(
        "job_teacher",
        WorkflowEvent("text_stage", "开始", "text_resources", status="running"),
    )
    service._record_event(
        "job_teacher",
        WorkflowEvent(
            "text_stage",
            "完成",
            "text_resources",
            {"classroom_intro": "完成"},
        ),
    )
    first = repository.get_events("job_teacher", after_id=0, limit=1)
    rest = repository.get_events(
        "job_teacher", after_id=first[-1]["id"], limit=10
    )
    assert first[0]["status"] == "running"
    assert rest[0]["status"] == "completed"
