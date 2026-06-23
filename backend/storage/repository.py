from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Callable, Optional

from backend.models import LearningJob, utc_now
from backend.storage.db import connect_target, initialize_schema


def _storage_key(value: Any, explicit_job_id: str | None) -> str:
    if explicit_job_id:
        return explicit_job_id
    if isinstance(value, dict):
        key = value.get("job_id")
    else:
        key = getattr(value, "job_id", None)
    if not key:
        raise ValueError("result or report must contain job_id")
    return str(key)


class InMemoryLearningRepository:
    """A process-local repository with atomic reads and writes."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[str, LearningJob] = {}
        self._results: dict[str, Any] = {}
        self._reports: dict[str, Any] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._feedback: dict[str, list[dict[str, Any]]] = {}
        self._answers: dict[str, dict[str, str]] = {}

    def create_job(self, job: LearningJob) -> LearningJob:
        with self._lock:
            if job.job_id in self._jobs:
                raise ValueError(f"duplicate job_id: {job.job_id}")
            self._jobs[job.job_id] = deepcopy(job)
            return deepcopy(job)

    def get_job(self, job_id: str) -> Optional[LearningJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job is not None else None

    def update_job(
        self, job_id: str, updater: Callable[[LearningJob], LearningJob]
    ) -> Optional[LearningJob]:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return None
            updated = updater(deepcopy(current))
            self._jobs[job_id] = deepcopy(updated)
            return deepcopy(updated)

    def save_result(self, result: Any, job_id: str | None = None) -> Any:
        with self._lock:
            key = _storage_key(result, job_id)
            self._results[key] = deepcopy(result)
            return deepcopy(result)

    def get_result(self, job_id: str) -> Optional[Any]:
        with self._lock:
            result = self._results.get(job_id)
            return deepcopy(result) if result is not None else None

    def save_report(self, report: Any, job_id: str | None = None) -> Any:
        with self._lock:
            key = _storage_key(report, job_id)
            self._reports[key] = deepcopy(report)
            return deepcopy(report)

    def get_report(self, job_id: str) -> Optional[Any]:
        with self._lock:
            report = self._reports.get(job_id)
            return deepcopy(report) if report is not None else None

    def list_jobs(
        self, *, role: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[LearningJob]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(), key=lambda item: item.created_at, reverse=True
            )
            if role:
                jobs = [job for job in jobs if job.role == role]
            return deepcopy(jobs[offset : offset + limit])

    def append_event(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            events = self._events.setdefault(job_id, [])
            stored = deepcopy(event)
            stored["id"] = len(events) + 1
            events.append(stored)
            return deepcopy(stored)

    def get_events(
        self, job_id: str, *, after_id: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(
                [
                    event
                    for event in self._events.get(job_id, [])
                    if int(event["id"]) > after_id
                ][:limit]
            )

    def save_feedback(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._feedback.setdefault(record["job_id"], []).append(deepcopy(record))
            return deepcopy(record)

    def save_quiz_answers(self, job_id: str, answers: dict[str, str]) -> None:
        with self._lock:
            self._answers[job_id] = deepcopy(answers)

    def save_job_context(
        self,
        job_id: str,
        *,
        poem: str,
        student_profile: dict[str, Any],
    ) -> None:
        return None


class SqliteLearningRepository:
    """Persistent runtime repository kept separate from generated files."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with connect_target(self.path) as conn:
            initialize_schema(conn)
            conn.execute(
                """
                UPDATE learning_jobs
                SET status = 'failed',
                    current_stage = 'failed',
                    message = 'gpu 任务因服务重启中断，请重新生成',
                    error_message = 'gpu 任务因服务重启中断，请重新生成',
                    updated_at = ?
                WHERE current_stage NOT IN ('completed', 'failed')
                """,
                (utc_now().isoformat(),),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return connect_target(self.path)

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> LearningJob:
        return LearningJob.model_validate(
            {
                "job_id": row["id"],
                "poem_id": row["poem_id"],
                "role": row["role"] if "role" in row.keys() else "student",
                "stage": row["current_stage"],
                "progress": row["progress"],
                "message": row["message"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "error": row["error_message"],
            }
        )

    def create_job(self, job: LearningJob) -> LearningJob:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_jobs (
                    id, poem_id, role, status, current_stage, progress, message,
                    error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.poem_id,
                    job.role,
                    job.stage.value,
                    job.stage.value,
                    job.progress,
                    job.message,
                    job.error,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job.model_copy(deep=True)

    def save_job_context(
        self,
        job_id: str,
        *,
        poem: str,
        student_profile: dict[str, Any],
    ) -> None:
        profile_id = f"profile_{job_id}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO student_profiles (
                    id, grade, level, weakness_json, goal, preference_json,
                    pretest_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    str(student_profile.get("grade") or ""),
                    str(student_profile.get("level") or ""),
                    json.dumps(
                        student_profile.get("weakness") or [],
                        ensure_ascii=False,
                    ),
                    str(student_profile.get("goal") or ""),
                    json.dumps(
                        student_profile.get("preferences") or {},
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        student_profile.get("pretest") or {},
                        ensure_ascii=False,
                    ),
                    utc_now().isoformat(),
                ),
            )
            conn.execute(
                """
                UPDATE learning_jobs
                SET poem_text = ?, student_profile_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (poem, profile_id, utc_now().isoformat(), job_id),
            )

    def get_job(self, job_id: str) -> Optional[LearningJob]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM learning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._job_from_row(row) if row is not None else None

    def list_jobs(
        self, *, role: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[LearningJob]:
        query = "SELECT * FROM learning_jobs"
        params: list[Any] = []
        if role:
            query += " WHERE role = ?"
            params.append(role)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._job_from_row(row) for row in rows]

    def append_event(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_events (
                    job_id, stage, agent_id, event_status, message,
                    output_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    event["stage"],
                    event.get("agent_id"),
                    event["status"],
                    event["message"],
                    (
                        json.dumps(event["output"], ensure_ascii=False)
                        if event.get("output") is not None
                        else None
                    ),
                    event["created_at"],
                ),
            )
            stored = {**event, "id": int(cursor.lastrowid)}
        return deepcopy(stored)

    def get_events(
        self, job_id: str, *, after_id: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ? AND id > ?
                ORDER BY id ASC LIMIT ?
                """,
                (job_id, after_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "stage": row["stage"],
                "agent_id": row["agent_id"],
                "status": row["event_status"],
                "message": row["message"],
                "output": (
                    json.loads(row["output_json"])
                    if row["output_json"] is not None
                    else None
                ),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_feedback(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feedback_records (
                    job_id, target_module, feedback, previous_output_json,
                    agent_input_json, updated_module_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["job_id"],
                    record["target_module"],
                    record["feedback"],
                    json.dumps(record["previous_output"], ensure_ascii=False),
                    json.dumps(record["agent_input"], ensure_ascii=False),
                    json.dumps(record["updated_module"], ensure_ascii=False),
                    record["created_at"],
                ),
            )
            stored = {**record, "feedback_id": int(cursor.lastrowid)}
        return deepcopy(stored)

    def save_quiz_answers(self, job_id: str, answers: dict[str, str]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiz_records SET answers_json = ? WHERE job_id = ?
                """,
                (json.dumps(answers, ensure_ascii=False), job_id),
            )

    def update_job(
        self,
        job_id: str,
        updater: Callable[[LearningJob], LearningJob],
    ) -> Optional[LearningJob]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM learning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            updated = updater(self._job_from_row(row))
            conn.execute(
                """
                UPDATE learning_jobs
                SET status = ?, current_stage = ?, progress = ?, message = ?,
                    error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.stage.value,
                    updated.stage.value,
                    updated.progress,
                    updated.message,
                    updated.error,
                    updated.updated_at.isoformat(),
                    job_id,
                ),
            )
        return updated.model_copy(deep=True)

    def save_result(self, result: Any, job_id: str | None = None) -> Any:
        key = _storage_key(result, job_id)
        payload = json.dumps(result, ensure_ascii=False)
        review_status = None
        if isinstance(result, dict):
            review_status = (
                result.get("final_review") or {}
            ).get("review_result")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generated_resources (
                    job_id, resource_type, content_json, review_status, created_at
                ) VALUES (?, 'learning_bundle', ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    content_json = excluded.content_json,
                    review_status = excluded.review_status,
                    created_at = excluded.created_at
                """,
                (key, payload, review_status, utc_now().isoformat()),
            )
            if isinstance(result, dict):
                self._save_structured_result(conn, key, result)
        return deepcopy(result)

    @staticmethod
    def _save_structured_result(
        conn: sqlite3.Connection,
        job_id: str,
        result: dict[str, Any],
    ) -> None:
        now = utc_now().isoformat()
        text_stage = result.get("text_stage") or {}
        agent_outputs = text_stage.get("agent_outputs") or {}
        conn.execute("DELETE FROM agent_outputs WHERE job_id = ?", (job_id,))
        for agent_name, output in agent_outputs.items():
            if agent_name == "quiz":
                stage = "quiz_generation"
            elif agent_name == "local_review":
                stage = "local_review"
            else:
                stage = "text_stage"
            confidence = (
                output.get("confidence")
                if isinstance(output, dict)
                else None
            )
            conn.execute(
                """
                INSERT INTO agent_outputs (
                    job_id, agent_name, stage, input_json, output_json,
                    confidence, created_at
                ) VALUES (?, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    job_id,
                    agent_name,
                    stage,
                    json.dumps(output, ensure_ascii=False),
                    confidence,
                    now,
                ),
            )

        prompt_snapshot = result.get("prompt_snapshot") or {}
        if prompt_snapshot:
            conn.execute(
                """
                INSERT INTO agent_outputs (
                    job_id, agent_name, stage, input_json, output_json,
                    confidence, created_at
                ) VALUES (?, 'kolors_prompt_compiler', 'image_prompt_compile',
                          ?, ?, NULL, ?)
                """,
                (
                    job_id,
                    json.dumps(
                        {
                            "initial": prompt_snapshot.get(
                                "initial_standard_prompt_json"
                            ),
                            "final": prompt_snapshot.get(
                                "final_standard_prompt_json"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "initial": prompt_snapshot.get(
                                "initial_kolors_prompt"
                            ),
                            "final": prompt_snapshot.get(
                                "final_kolors_prompt"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )

        quiz = agent_outputs.get("quiz")
        if quiz is not None:
            conn.execute(
                """
                INSERT INTO quiz_records (
                    job_id, quiz_json, report_json, created_at
                ) VALUES (?, ?, '{}', ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    quiz_json = excluded.quiz_json
                """,
                (job_id, json.dumps(quiz, ensure_ascii=False), now),
            )

        image = result.get("image") or {}
        image_path = image.get("image_path")
        if image_path:
            conn.execute("DELETE FROM image_outputs WHERE job_id = ?", (job_id,))
            conn.execute(
                """
                INSERT INTO image_outputs (
                    job_id, image_path, image_url, prompt, negative_prompt,
                    seed, vision_review_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    image_path,
                    f"/api/image?path={image_path}",
                    image.get("prompt") or "",
                    image.get("negative_prompt") or "",
                    image.get("seed"),
                    json.dumps(
                        result.get("vision_review") or {},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )

        conn.execute("DELETE FROM review_records WHERE job_id = ?", (job_id,))
        local_review = agent_outputs.get("local_review")
        if local_review is not None:
            conn.execute(
                """
                INSERT INTO review_records (
                    job_id, reviewer, review_type, output_json, pass, created_at
                ) VALUES (?, 'qwen2.5-14b-awq-local', 'local_initial',
                          ?, ?, ?)
                """,
                (
                    job_id,
                    json.dumps(local_review, ensure_ascii=False),
                    int(bool(local_review.get("pass"))),
                    now,
                ),
            )
        text_review = result.get("text_review")
        if isinstance(text_review, dict):
            conn.execute(
                """
                INSERT INTO review_records (
                    job_id, reviewer, review_type, output_json, pass, created_at
                ) VALUES (?, ?, 'text_review', ?, ?, ?)
                """,
                (
                    job_id,
                    str(text_review.get("reviewer") or "unknown"),
                    json.dumps(text_review, ensure_ascii=False),
                    int(bool(text_review.get("pass"))),
                    now,
                ),
            )
        vision_review = result.get("vision_review")
        if isinstance(vision_review, dict):
            vision_output = vision_review.get("output") or {}
            conn.execute(
                """
                INSERT INTO review_records (
                    job_id, reviewer, review_type, output_json, pass, created_at
                ) VALUES (?, 'qwen2.5-vl-7b-instruct', 'vision_review',
                          ?, ?, ?)
                """,
                (
                    job_id,
                    json.dumps(vision_review, ensure_ascii=False),
                    int(bool(vision_output.get("pass"))),
                    now,
                ),
            )
        final_decision = (
            result.get("final_decision") or result.get("final_review")
        )
        if isinstance(final_decision, dict):
            conn.execute(
                """
                INSERT INTO review_records (
                    job_id, reviewer, review_type, output_json, pass, created_at
                ) VALUES (?, 'workflow_gate', 'final_decision', ?, ?, ?)
                """,
                (
                    job_id,
                    json.dumps(final_decision, ensure_ascii=False),
                    int(bool(final_decision.get("pass"))),
                    now,
                ),
            )

    def get_result(self, job_id: str) -> Optional[Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_json FROM generated_resources WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return json.loads(row["content_json"]) if row is not None else None

    def save_report(self, report: Any, job_id: str | None = None) -> Any:
        key = _storage_key(report, job_id)
        weak_points = report.get("weak_points", []) if isinstance(report, dict) else []
        score = report.get("objective_score") if isinstance(report, dict) else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_records (
                    job_id, score, weak_points_json, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    score = excluded.score,
                    weak_points_json = excluded.weak_points_json,
                    report_json = excluded.report_json,
                    created_at = excluded.created_at
                """,
                (
                    key,
                    score,
                    json.dumps(weak_points, ensure_ascii=False),
                    json.dumps(report, ensure_ascii=False),
                    utc_now().isoformat(),
                ),
            )
        return deepcopy(report)

    def get_report(self, job_id: str) -> Optional[Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM quiz_records WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return json.loads(row["report_json"]) if row is not None else None
    @staticmethod
    def _storage_key(value: Any, explicit_job_id: str | None) -> str:
        if explicit_job_id:
            return explicit_job_id
        if isinstance(value, dict):
            key = value.get("job_id")
        else:
            key = getattr(value, "job_id", None)
        if not key:
            raise ValueError("result or report must contain job_id")
        return str(key)
