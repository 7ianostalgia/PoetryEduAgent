from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.models import LearningJob, LearningStage, utc_now
from backend.storage import SqliteLearningRepository


def test_sqlite_repository_persists_job_result_and_report(tmp_path: Path) -> None:
    path = tmp_path / "runtime.db"
    repository = SqliteLearningRepository(path)
    now = utc_now()
    job = LearningJob(
        job_id="job_persistent",
        poem_id="jing-ye-si",
        stage=LearningStage.QUEUED,
        progress=0,
        message="等待中",
        created_at=now,
        updated_at=now,
    )
    repository.create_job(job)
    repository.append_event(
        job.job_id,
        {
            "stage": "queued",
            "agent_id": "poem_analysis",
            "status": "running",
            "message": "等待中",
            "output": None,
            "created_at": now.isoformat(),
        },
    )
    repository.save_job_context(
        job.job_id,
        poem="床前明月光",
        student_profile={
            "grade": "七年级",
            "level": "basic",
            "weakness": ["imagery_analysis"],
            "goal": "understand",
            "preferences": {"needs_visual_support": True},
        },
    )
    repository.update_job(
        job.job_id,
        lambda current: current.model_copy(
            update={
                "stage": LearningStage.COMPLETED,
                "progress": 100,
                "message": "已完成",
                "updated_at": utc_now(),
            }
        ),
    )
    repository.save_result(
        {
            "job_id": job.job_id,
            "text_stage": {
                "agent_outputs": {
                    "student_diagnosis": {"confidence": 0.9},
                    "quiz": {
                        "objective_questions": [],
                        "subjective_questions": [],
                    },
                    "local_review": {"pass": True},
                }
            },
            "image": {
                "image_path": "/tmp/output.png",
                "prompt": "月夜",
                "negative_prompt": "现代物件",
                "seed": 7,
            },
            "prompt_snapshot": {
                "initial_standard_prompt_json": {"scene": "月夜"},
                "initial_kolors_prompt": {
                    "zh_prompt": "古代月夜场景",
                    "negative_prompt": "现代元素",
                },
                "final_standard_prompt_json": {"scene": "月夜"},
                "final_kolors_prompt": {
                    "zh_prompt": "古代月夜场景",
                    "negative_prompt": "现代元素",
                },
            },
            "vision_review": {"output": {"moon": True}},
            "final_review": {
                "reviewer": "local",
                "review_result": "pass",
                "pass": True,
            },
        }
    )
    repository.save_report(
        {
            "job_id": job.job_id,
            "objective_score": 2,
            "weak_points": [],
        }
    )
    repository.save_quiz_answers(job.job_id, {"obj_1": "A"})

    reopened = SqliteLearningRepository(path)
    assert reopened.get_job(job.job_id).stage == LearningStage.COMPLETED
    assert reopened.get_result(job.job_id)["final_review"]["review_result"] == "pass"
    assert reopened.get_report(job.job_id)["objective_score"] == 2
    assert reopened.list_jobs(role="student")[0].job_id == job.job_id
    assert reopened.get_events(job.job_id)[0]["status"] == "running"

    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT poem_text FROM learning_jobs WHERE id = ?",
            (job.job_id,),
        ).fetchone()[0] == "床前明月光"
        assert conn.execute("SELECT COUNT(*) FROM student_profiles").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_outputs").fetchone()[0] == 4
        compiler_row = conn.execute(
            """
            SELECT input_json, output_json
            FROM agent_outputs
            WHERE agent_name = 'kolors_prompt_compiler'
            """
        ).fetchone()
        assert "scene" in compiler_row[0]
        assert "zh_prompt" in compiler_row[1]
        assert conn.execute("SELECT COUNT(*) FROM image_outputs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM review_records").fetchone()[0] == 3
        quiz = conn.execute(
            "SELECT quiz_json, answers_json, report_json FROM quiz_records"
        ).fetchone()
        assert "objective_questions" in quiz[0]
        assert json.loads(quiz[1]) == {"obj_1": "A"}
        assert "objective_score" in quiz[2]


def test_runtime_schema_contains_required_tables(tmp_path: Path) -> None:
    path = tmp_path / "runtime.db"
    SqliteLearningRepository(path)
    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "student_profiles",
        "learning_jobs",
        "agent_outputs",
        "generated_resources",
        "image_outputs",
        "review_records",
        "quiz_records",
        "question_templates",
        "job_events",
        "feedback_records",
    } <= tables


def test_runtime_schema_normalizes_legacy_mode_messages(tmp_path: Path) -> None:
    path = tmp_path / "runtime.db"
    SqliteLearningRepository(path)
    now = utc_now().isoformat()
    legacy_mode_label = "\u771f\u5b9e"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO learning_jobs (
                id, poem_id, role, status, current_stage, progress, message,
                error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job_legacy_mode",
                "jing-ye-si",
                "student",
                "completed",
                "completed",
                100,
                f"{legacy_mode_label}学习资源流水线已完成",
                None,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO job_events (
                job_id, stage, agent_id, event_status, message,
                output_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job_legacy_mode",
                "queued",
                "poem_analysis",
                "waiting",
                f"{legacy_mode_label}任务已创建，正在等待 GPU",
                None,
                now,
            ),
        )

    repository = SqliteLearningRepository(path)

    assert repository.get_job("job_legacy_mode").message == (
        "gpu 学习资源流水线已完成"
    )
    assert repository.get_events("job_legacy_mode")[0]["message"] == (
        "gpu 任务已创建，正在等待 GPU"
    )


def test_runtime_repository_marks_interrupted_jobs_failed_on_reopen(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.db"
    repository = SqliteLearningRepository(path)
    now = utc_now()
    repository.create_job(
        LearningJob(
            job_id="job_interrupted",
            poem_id="jing-ye-si",
            stage=LearningStage.TEXT_STAGE,
            progress=15,
            message="Qwen 正在分析诗句与学生画像",
            created_at=now,
            updated_at=now,
        )
    )

    reopened = SqliteLearningRepository(path)
    job = reopened.get_job("job_interrupted")

    assert job.stage == LearningStage.FAILED
    assert job.message == "gpu 任务因服务重启中断，请重新生成"
    assert job.error == "gpu 任务因服务重启中断，请重新生成"
