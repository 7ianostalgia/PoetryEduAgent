from __future__ import annotations

import json
import logging
import io
import zipfile
from copy import deepcopy
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Optional
from uuid import uuid4

from backend.model_clients import QwenAwqClient, QwenTextRequest
from backend.agents.text_stage import TEXT_STAGE_SCHEMA
from backend.models import (
    CreateLearningJobRequest,
    LearningJob,
    LearningStage,
    QuizSubmission,
    utc_now,
)
from backend.orchestration.gpu_workflow import (
    GpuLearningWorkflow,
    build_final_decision,
    WorkflowEvent,
)
from backend.storage import InMemoryLearningRepository


logger = logging.getLogger(__name__)

QUIZ_REPORT_SCHEMA = {
    "type": "object",
    "required": [
        "subjective_scores",
        "weak_points",
        "diagnosis",
        "next_learning_path",
    ],
    "properties": {
        "subjective_scores": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["question_id", "score", "feedback"],
                "properties": {
                    "question_id": {"type": "string"},
                    "score": {"type": "number"},
                    "feedback": {"type": "string"},
                },
            },
        },
        "weak_points": {"type": "array", "items": {"type": "string"}},
        "diagnosis": {"type": "string"},
        "next_learning_path": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string"},
        },
    },
}


STAGE_PROGRESS = {
    "text_stage": 15,
    "image_generation": 45,
    "vision_review": 65,
    "deepseek_review": 78,
    "local_review_d2": 85,
    "image_correction": 90,
}

RESOURCE_DEFAULTS = {
    "teaching_goals": [],
    "teaching_key_difficulties": {"key_points": [], "difficulties": []},
    "classroom_activities": [],
}

TARGET_ALIASES = {
    "teaching重点难点": "teaching_key_difficulties",
}

TARGET_SCHEMAS = {
    "classroom_intro": {"type": "string"},
    "layered_explanations": TEXT_STAGE_SCHEMA["properties"]["learning_resources"][
        "properties"
    ]["layered_explanations"],
    "guided_questions": TEXT_STAGE_SCHEMA["properties"]["learning_resources"][
        "properties"
    ]["guided_questions"],
    "teaching_goals": TEXT_STAGE_SCHEMA["properties"]["learning_resources"][
        "properties"
    ]["teaching_goals"],
    "teaching_key_difficulties": TEXT_STAGE_SCHEMA["properties"][
        "learning_resources"
    ]["properties"]["teaching_key_difficulties"],
    "classroom_activities": TEXT_STAGE_SCHEMA["properties"][
        "learning_resources"
    ]["properties"]["classroom_activities"],
    "quiz": TEXT_STAGE_SCHEMA["properties"]["quiz"],
}


def _with_resource_defaults(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    normalized = deepcopy(result)
    resources = (
        (normalized.get("text_stage") or {})
        .get("agent_outputs", {})
        .get("learning_resources")
    )
    if isinstance(resources, dict):
        for key, value in RESOURCE_DEFAULTS.items():
            resources.setdefault(key, deepcopy(value))
    return normalized


class GpuLearningService:
    run_mode = "gpu"

    def __init__(
        self,
        repository: InMemoryLearningRepository,
        workflow: GpuLearningWorkflow,
        qwen_client: QwenAwqClient | None = None,
    ) -> None:
        self._repository = repository
        self._workflow = workflow
        self._qwen_client = qwen_client or QwenAwqClient()
        self._event_lock = RLock()

    @property
    def deepseek_configured(self) -> bool:
        client = getattr(self._workflow, "deepseek_client", None)
        return bool(getattr(client, "configured", False))

    def create_job(self, payload: CreateLearningJobRequest) -> LearningJob:
        now = utc_now()
        job = LearningJob(
            job_id=f"job_{uuid4().hex[:16]}",
            poem_id=payload.poem_id,
            role=payload.role,
            stage=LearningStage.QUEUED,
            progress=0,
            message="gpu 任务已创建，正在等待 GPU",
            created_at=now,
            updated_at=now,
        )
        self._repository.create_job(job)
        self._record_event(
            job.job_id,
            WorkflowEvent(
                "queued",
                job.message,
                "poem_analysis",
                status="waiting",
            ),
        )
        profile = payload.student_profile.model_dump()
        profile["audience_role"] = payload.role
        profile["custom_requirements"] = payload.custom_requirements
        self._repository.save_job_context(
            job.job_id,
            poem=payload.poem,
            student_profile=profile,
        )
        Thread(
            target=self._run,
            args=(job.job_id, payload),
            daemon=True,
            name=f"gpu-learning-{job.job_id}",
        ).start()
        return job

    def get_job(self, job_id: str) -> Optional[LearningJob]:
        return self._repository.get_job(job_id)

    def get_result(self, job_id: str) -> Any:
        return _with_resource_defaults(self._repository.get_result(job_id))

    def get_report(self, job_id: str) -> Any:
        return self._repository.get_report(job_id)

    def _record_event(self, job_id: str, event: WorkflowEvent) -> None:
        payload = {
            "stage": event.stage,
            "agent_id": event.agent_id,
            "status": (
                event.status
                or ("completed" if event.output is not None else "running")
            ),
            "message": event.message,
            "output": deepcopy(event.output),
            "created_at": utc_now().isoformat(),
        }
        with self._event_lock:
            self._repository.append_event(job_id, payload)

    def get_events(
        self, job_id: str, *, after_id: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._event_lock:
            return self._repository.get_events(
                job_id, after_id=after_id, limit=limit
            )

    def list_jobs(
        self, *, role: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[LearningJob]:
        return self._repository.list_jobs(role=role, limit=limit, offset=offset)

    def _update(self, job_id: str, event: WorkflowEvent) -> None:
        self._record_event(job_id, event)
        if event.stage == "completed":
            return
        stage = LearningStage(event.stage)

        def apply(job: LearningJob) -> LearningJob:
            return job.model_copy(
                update={
                    "stage": stage,
                    "progress": max(
                        job.progress,
                        STAGE_PROGRESS[event.stage],
                    ),
                    "message": event.message,
                    "updated_at": utc_now(),
                    "error": None,
                }
            )

        self._repository.update_job(job_id, apply)

    def _run(self, job_id: str, payload: CreateLearningJobRequest) -> None:
        try:
            profile = payload.student_profile.model_dump()
            profile["audience_role"] = payload.role
            profile["custom_requirements"] = payload.custom_requirements
            result = self._workflow.run(
                poem=payload.poem,
                student_profile=profile,
                job_id=job_id,
                on_event=lambda event: self._update(job_id, event),
            )
            result["role"] = payload.role
            result["custom_requirements"] = payload.custom_requirements
            result = _with_resource_defaults(result)
            self._repository.save_result(result, job_id)

            def complete(job: LearningJob) -> LearningJob:
                return job.model_copy(
                    update={
                        "stage": LearningStage.COMPLETED,
                        "progress": 100,
                        "message": "gpu 学习资源流水线已完成",
                        "updated_at": utc_now(),
                        "error": None,
                    }
                )

            self._repository.update_job(job_id, complete)
            self._record_event(
                job_id,
                WorkflowEvent(
                    "completed",
                    "gpu 学习资源流水线已完成",
                    status="completed",
                ),
            )
        except Exception as exc:
            logger.exception("gpu 学习任务 %s 执行失败", job_id)
            self._record_event(
                job_id,
                WorkflowEvent(
                    "failed",
                    "gpu 任务执行失败，详细错误已写入服务器日志",
                    status="failed",
                ),
            )
            raw_error = str(exc)
            if (
                "模型输出无法解析为 JSON 对象" in raw_error
                or "视觉模型连续三次未返回合法 JSON" in raw_error
            ):
                public_error = "视觉模型多次未返回合法 JSON，请重新生成"
            elif len(raw_error) > 500:
                public_error = "模型阶段执行失败，详细原因已写入服务器日志"
            else:
                public_error = raw_error

            def fail(job: LearningJob) -> LearningJob:
                return job.model_copy(
                    update={
                        "stage": LearningStage.FAILED,
                        "message": "gpu 任务执行失败",
                        "updated_at": utc_now(),
                        "error": public_error,
                    }
                )

            self._repository.update_job(job_id, fail)

    def submit_quiz(
        self,
        job_id: str,
        submission: QuizSubmission,
    ) -> dict[str, Any]:
        result = self.get_result(job_id)
        if not result:
            raise ValueError("任务结果尚未生成")
        quiz = result["text_stage"]["agent_outputs"]["quiz"]
        questions = {
            item["id"]: item
            for kind in ("objective_questions", "subjective_questions")
            for item in quiz[kind]
        }
        answers = {
            item.question_id: item.answer
            for item in submission.answers
        }
        if set(answers) != set(questions):
            raise ValueError("提交的题目 ID 与当前任务不一致")

        objective_score = 0
        objective_details = []
        for item in quiz["objective_questions"]:
            correct = answers[item["id"]].strip().upper() == item["answer"]
            objective_score += int(correct)
            objective_details.append(
                {
                    "question_id": item["id"],
                    "correct": correct,
                    "answer": item["answer"],
                    "explanation": item["explanation"],
                }
            )

        subjective_payload = [
            {
                "question": item,
                "student_answer": answers[item["id"]],
            }
            for item in quiz["subjective_questions"]
        ]
        grading = self._qwen_client.run_text(
            QwenTextRequest(
                task_name="quiz_feedback",
                system_prompt=(
                    "你是中学语文教师。严格按 rubric 给两道主观题评分，"
                    "指出薄弱点并给出下一步学习路径。"
                ),
                user_prompt=json.dumps(
                    {
                        "poem": result["poem"],
                        "student_profile": result["student_profile"],
                        "subjective_answers": subjective_payload,
                    },
                    ensure_ascii=False,
                ),
                output_schema=QUIZ_REPORT_SCHEMA,
                max_input_tokens=4096,
                max_new_tokens=768,
                temperature=0.0,
            )
        ).output
        subjective_total = sum(
            int(item.get("total_score") or 5)
            for item in quiz["subjective_questions"]
        )
        subjective_score = sum(
            float(item.get("score") or 0)
            for item in grading.get("subjective_scores", [])
        )
        max_score = 2 + subjective_total
        earned_score = objective_score + subjective_score
        report = {
            "job_id": job_id,
            "objective_score": objective_score,
            "objective_total": 2,
            "objective_details": objective_details,
            "subjective_score": subjective_score,
            "subjective_total": subjective_total,
            "earned_score": earned_score,
            "max_score": max_score,
            "score": round(earned_score / max_score * 100),
            **grading,
        }
        self._repository.save_report(report, job_id)
        self._repository.save_quiz_answers(job_id, answers)
        return report

    def apply_feedback(
        self, job_id: str, *, target_module: str, feedback: str
    ) -> dict[str, Any]:
        result = self.get_result(job_id)
        if not isinstance(result, dict):
            raise ValueError("任务结果尚未生成")
        canonical = TARGET_ALIASES.get(target_module, target_module)
        if canonical not in TARGET_SCHEMAS:
            raise ValueError("不支持的目标模块")
        outputs = result["text_stage"]["agent_outputs"]
        container = outputs if canonical == "quiz" else outputs["learning_resources"]
        previous_output = deepcopy(container.get(canonical))
        structured_input = {
            "target_module": canonical,
            "previous_output": previous_output,
            "teacher_feedback": feedback,
            "poem": result.get("poem"),
            "student_profile": result.get("student_profile") or {},
            "preserve_instruction": (
                "只修改 target_module，其他所有模块保持原样"
            ),
        }
        self._update(
            job_id,
            WorkflowEvent(
                "text_stage",
                "资源生成 Agent 正在根据教师反馈定向修改",
                "text_resources",
                status="running",
            ),
        )
        response = self._qwen_client.run_text(
            QwenTextRequest(
                task_name=f"teacher_feedback_{canonical}",
                system_prompt=(
                    "你是定向教学资源修订 Agent。只能修订 target_module 指定模块，"
                    "不得建议、输出或改写其他模块。忠实保留未被教师反馈要求改变的内容。"
                ),
                user_prompt=json.dumps(structured_input, ensure_ascii=False),
                output_schema={
                    "type": "object",
                    "required": ["updated_module"],
                    "additionalProperties": False,
                    "properties": {
                        "updated_module": TARGET_SCHEMAS[canonical],
                    },
                },
                max_input_tokens=6144,
                max_new_tokens=1536,
                temperature=0.1,
            )
        )
        updated_module = deepcopy(response.output["updated_module"])
        container[canonical] = updated_module
        self._update(
            job_id,
            WorkflowEvent(
                "text_stage",
                "教师指定模块已重新生成",
                "text_resources",
                {"target_module": canonical, "updated_module": updated_module},
            ),
        )
        text_review = self._workflow._run_text_review(
            review_input=self._workflow._text_review_input(
                poem=str(result.get("poem") or ""),
                student_profile=result.get("student_profile") or {},
                text_result=result["text_stage"],
            ),
            emit=lambda event: self._update(job_id, event),
        )
        review_stage = (
            "local_review_d2"
            if text_review.get("fallback_used")
            else "deepseek_review"
        )
        self._update(
            job_id,
            WorkflowEvent(
                review_stage,
                "教师反馈后的文字资源复审完成",
                "text_reviewer",
                text_review,
            ),
        )
        result["text_review"] = text_review
        vision_review = (result.get("vision_review") or {}).get("output") or {}
        final_decision = build_final_decision(
            text_review=text_review,
            vision_review=vision_review,
        )
        result["final_decision"] = final_decision
        result["final_review"] = {
            **text_review,
            "review_result": (
                "pass" if final_decision["pass"] else "needs_revision"
            ),
            **final_decision,
        }
        self._repository.save_result(result, job_id)
        self._repository.update_job(
            job_id,
            lambda job: job.model_copy(
                update={
                    "stage": LearningStage.COMPLETED,
                    "progress": 100,
                    "message": "教师反馈模块已重生成并完成文字复审",
                    "updated_at": utc_now(),
                    "error": None,
                }
            ),
        )
        self._record_event(
            job_id,
            WorkflowEvent(
                "completed",
                "教师反馈模块已重生成并完成文字复审",
                "final_gate",
                final_decision,
                "completed",
            ),
        )
        evidence = {
            "target_module": canonical,
            "previous_output_included": previous_output is not None,
            "teacher_feedback_included_verbatim": True,
            "teacher_feedback_length": len(feedback),
            "immutable_sibling_modules": sorted(
                key for key in container if key != canonical
            ),
        }
        self._repository.save_feedback(
            {
                "job_id": job_id,
                "target_module": canonical,
                "feedback": feedback,
                "previous_output": previous_output,
                "agent_input": structured_input,
                "updated_module": updated_module,
                "created_at": utc_now().isoformat(),
            }
        )
        return {
            "job_id": job_id,
            "target_module": canonical,
            "agent_input": evidence,
            "updated_module": updated_module,
        }

    def build_teacher_package(self, job_id: str) -> bytes:
        result = self.get_result(job_id)
        if not isinstance(result, dict):
            raise ValueError("任务结果尚未生成")
        outputs = (result.get("text_stage") or {}).get("agent_outputs") or {}
        resources = deepcopy(outputs.get("learning_resources") or {})
        for private_key in (
            "standard_prompt_json",
            "image_prompt",
            "quality_prompts",
        ):
            resources.pop(private_key, None)
        review = result.get("final_decision") or result.get("final_review") or {}
        summary = {
            key: review.get(key)
            for key in ("pass", "text_pass", "vision_pass", "failed_parts")
            if key in review
        }
        difficulties = resources.get("teaching_key_difficulties") or {}
        activities = resources.get("classroom_activities") or []
        markdown = [
            "# 教师资源包",
            "",
            "## 课堂导入",
            str(resources.get("classroom_intro") or "暂无"),
            "",
            "## 教学目标",
            *[
                f"{index}. {item}"
                for index, item in enumerate(
                    resources.get("teaching_goals") or [], 1
                )
            ],
            "",
            "## 教学重点",
            *[
                f"- {item}"
                for item in difficulties.get("key_points") or []
            ],
            "",
            "## 教学难点",
            *[
                f"- {item}"
                for item in difficulties.get("difficulties") or []
            ],
            "",
            "## 分层讲解",
            *[
                f"- {label}：{(resources.get('layered_explanations') or {}).get(key, '暂无')}"
                for key, label in (
                    ("basic", "基础层"),
                    ("medium", "进阶层"),
                    ("advanced", "拓展层"),
                )
            ],
            "",
            "## 启发式问题链",
            *[
                f"{index}. {item}"
                for index, item in enumerate(
                    resources.get("guided_questions") or [], 1
                )
            ],
            "",
            "## 课堂活动",
        ]
        for index, activity in enumerate(activities, 1):
            if isinstance(activity, dict):
                markdown.extend(
                    [
                        f"### {index}. {activity.get('name') or '课堂活动'}",
                        *[
                            f"- {step}"
                            for step in activity.get("procedure") or []
                        ],
                        f"- 目的：{activity.get('purpose') or '暂无'}",
                    ]
                )
            else:
                markdown.append(f"{index}. {activity}")
        markdown.extend(
            [
                "",
                "## 审核结果",
                f"- 审核状态：{'通过' if summary.get('pass') else '需要复核'}",
                f"- 文本审核：{'通过' if summary.get('text_pass') else '需要复核'}",
                f"- 图像审核：{'通过' if summary.get('vision_pass') else '需要复核'}",
                f"- 风险提示：{'无明显问题' if summary.get('pass') else '请检查标记项'}",
                f"- 建议：{'可直接用于课堂展示' if summary.get('pass') else '教师复核后使用'}",
                "",
            ]
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "教师资源包.md",
                "\n".join(markdown),
            )
            archive.writestr(
                "resources.json",
                json.dumps(resources, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                "quiz.json",
                json.dumps(outputs.get("quiz") or {}, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                "review_summary.json",
                json.dumps(summary, ensure_ascii=False, indent=2),
            )
            image_path = Path(
                (result.get("image") or {}).get("image_path") or ""
            ).expanduser().resolve()
            output_root = Path(
                getattr(self._workflow, "output_root", image_path.parent)
            ).expanduser().resolve()
            if (
                output_root in image_path.parents
                and image_path.is_file()
                and image_path.suffix.lower()
                in {".png", ".jpg", ".jpeg", ".webp"}
            ):
                archive.write(image_path, f"images/{image_path.name}")
        return buffer.getvalue()
