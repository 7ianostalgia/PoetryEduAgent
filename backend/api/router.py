from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from backend.models import (
    CreateLearningJobRequest,
    LegacyCreateJobRequest,
    LegacyCreatedJob,
    LegacyJob,
    LegacyLearningResult,
    LegacyQuiz,
    LegacyQuizQuestion,
    LearningJob,
    LearningStage,
    QuizSubmission,
    TeacherFeedbackRequest,
)


router = APIRouter(prefix="/api")
public_router = APIRouter()


LEGACY_STAGE_MAP = {
    LearningStage.QUEUED: "queued",
    LearningStage.ANALYZING: "running",
    LearningStage.GENERATING_RESOURCES: "running",
    LearningStage.GENERATING_QUIZ: "running",
    LearningStage.COMPLETED: "succeeded",
    LearningStage.FAILED: "failed",
}


def _service(request: Request):
    return request.app.state.learning_service


def _require_job(service, job_id: str) -> LearningJob:
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="learning job not found")
    return job


def _require_result(service, job_id: str):
    job = _require_job(service, job_id)
    result = service.get_result(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "learning result is not ready",
                "stage": job.stage.value,
                "progress": job.progress,
            },
        )
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


AGENT_DEFINITIONS = (
    ("poem_analysis", "诗句解析 Agent", "text"),
    ("image_prompt", "意象提取 Agent", "image"),
    ("prompt_compiler", "Kolors Prompt 编译器", "image"),
    ("kolors", "Kolors 生图 Agent", "image"),
    ("vision_reviewer", "Qwen-VL 图片审核 Agent", "image"),
    ("text_resources", "课堂资源 Agent", "text"),
    ("text_reviewer", "DeepSeek / Qwen 文字审核 Agent", "text"),
    ("final_gate", "双门禁判定模块", "gate"),
)


def _agent_outputs(result: dict | None) -> dict[str, object]:
    if not isinstance(result, dict):
        return {}
    text_stage = result.get("text_stage") or {}
    outputs = text_stage.get("agent_outputs") or {}
    resources = outputs.get("learning_resources") or {}
    image = result.get("image") or {}
    return {
        "poem_analysis": {
            "student_diagnosis": outputs.get("student_diagnosis"),
            "poem_analysis": outputs.get("poem_analysis"),
        },
        "image_prompt": (
            (result.get("prompt_snapshot") or {}).get(
                "final_standard_prompt_json"
            )
            or resources.get("standard_prompt_json")
        ),
        "prompt_compiler": (
            (result.get("prompt_snapshot") or {}).get("final_kolors_prompt")
            or resources.get("image_prompt")
        ),
        "kolors": {
            key: image.get(key)
            for key in (
                "image_path",
                "seed",
                "steps",
                "guidance_scale",
                "width",
                "height",
            )
            if image.get(key) is not None
        },
        "vision_reviewer": result.get("vision_review"),
        "text_resources": {
            "audience_role": result.get("role")
            or (result.get("student_profile") or {}).get("audience_role"),
            "learning_resources": resources,
            "quiz": outputs.get("quiz"),
        },
        "text_reviewer": result.get("text_review"),
        "final_gate": result.get("final_decision")
        or result.get("final_review"),
    }


def _agent_statuses(
    job: LearningJob, events: list[dict[str, object]]
) -> dict[str, str]:
    statuses = {agent_id: "waiting" for agent_id, _, _ in AGENT_DEFINITIONS}
    for event in events:
        agent_id = event.get("agent_id")
        event_status = event.get("status")
        if agent_id in statuses and event_status in {
            "waiting",
            "running",
            "completed",
            "failed",
        }:
            statuses[str(agent_id)] = str(event_status)
    if job.stage == LearningStage.FAILED:
        running = [key for key, value in statuses.items() if value == "running"]
        if running:
            statuses[running[-1]] = "failed"
    return statuses


@router.get("/health")
def health(request: Request) -> dict:
    service = _service(request)
    return {
        "status": "ok",
        "service": "PoetryEduAgent",
        "run_mode": service.run_mode,
        "deepseek_configured": bool(
            getattr(service, "deepseek_configured", False)
        ),
    }


@router.get("/config")
def runtime_config(request: Request) -> dict:
    service = _service(request)
    app_settings = request.app.state.settings
    port = int(app_settings.port)
    return {
        "service": "PoetryEduAgent",
        "run_mode": service.run_mode,
        "host": app_settings.host,
        "port": port,
        "frontend": f"http://localhost:{port}",
        "api_docs": f"http://localhost:{port}/docs",
        "deepseek_configured": bool(
            getattr(service, "deepseek_configured", False)
        ),
    }


@public_router.get("/health")
def legacy_health(request: Request) -> dict:
    service = _service(request)
    return {
        "status": "ok",
        "run_mode": service.run_mode,
        "service": "poetry-edu-agent",
    }


@router.post(
    "/learning/jobs",
    response_model=LearningJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_learning_job(
    payload: CreateLearningJobRequest, request: Request
) -> LearningJob:
    service = _service(request)
    return service.create_job(payload)


@router.get("/learning/jobs")
def list_learning_jobs(
    request: Request,
    role: str | None = Query(default=None, pattern="^(teacher|student)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    service = _service(request)
    jobs = service.list_jobs(role=role, limit=limit, offset=offset)
    return [
        {
            **job.model_dump(mode="json"),
            "title": "静夜思" if job.poem_id == "jing-ye-si" else job.poem_id,
            "has_result": service.get_result(job.job_id) is not None,
            "has_report": service.get_report(job.job_id) is not None,
        }
        for job in jobs
    ]


@router.get("/learning/jobs/{job_id}", response_model=LearningJob)
def get_learning_job(job_id: str, request: Request) -> LearningJob:
    return _require_job(_service(request), job_id)


@router.get("/learning/jobs/{job_id}/events")
def get_learning_events(
    job_id: str,
    request: Request,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
):
    service = _service(request)
    _require_job(service, job_id)
    events = service.get_events(job_id, after_id=after_id, limit=limit)
    return {
        "job_id": job_id,
        "events": events,
        "next_after_id": events[-1]["id"] if events else after_id,
    }


@router.get("/learning/jobs/{job_id}/events/stream")
def stream_learning_events(
    job_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    service = _service(request)
    _require_job(service, job_id)
    try:
        initial_id = max(0, int(last_event_id or "0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid Last-Event-ID") from exc

    async def event_stream():
        cursor = initial_id
        idle_rounds = 0
        while True:
            if await request.is_disconnected():
                break
            events = service.get_events(job_id, after_id=cursor, limit=200)
            if events:
                idle_rounds = 0
                for event in events:
                    cursor = int(event["id"])
                    yield (
                        f"id: {cursor}\n"
                        "event: workflow_event\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )
            else:
                idle_rounds += 1
                job = service.get_job(job_id)
                if job and job.stage in {
                    LearningStage.COMPLETED,
                    LearningStage.FAILED,
                }:
                    break
                if idle_rounds % 15 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/learning/jobs/{job_id}/result",
)
def get_learning_result(job_id: str, request: Request):
    service = _service(request)
    job = _require_job(service, job_id)
    if job.stage == LearningStage.FAILED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=job.error or "learning job failed",
        )
    result = service.get_result(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "learning result is not ready",
                "stage": job.stage.value,
                "progress": job.progress,
            },
        )
    return result


@router.get("/learning/jobs/{job_id}/overview")
def get_learning_overview(job_id: str, request: Request):
    service = _service(request)
    job = _require_job(service, job_id)
    result = service.get_result(job_id)
    payload = (
        result.model_dump(mode="json")
        if hasattr(result, "model_dump")
        else result
    )
    return {
        "job": job,
        "ready": payload is not None,
        "final_decision": (
            (payload.get("final_decision") or payload.get("final_review"))
            if isinstance(payload, dict)
            else None
        ),
        "sections": {
            "rag": f"/api/learning/jobs/{job_id}/rag",
            "text": f"/api/learning/jobs/{job_id}/text",
            "image": f"/api/learning/jobs/{job_id}/image-result",
            "reviews": f"/api/learning/jobs/{job_id}/reviews",
            "quiz": f"/api/learning/jobs/{job_id}/quiz",
            "report": f"/api/learning/jobs/{job_id}/report",
        },
    }


@router.get("/learning/jobs/{job_id}/agents")
def get_learning_agents(job_id: str, request: Request):
    service = _service(request)
    job = _require_job(service, job_id)
    raw_result = service.get_result(job_id)
    result = (
        raw_result.model_dump(mode="json")
        if hasattr(raw_result, "model_dump")
        else raw_result
    )
    outputs = _agent_outputs(result)
    events = (
        service.get_events(job_id)
        if hasattr(service, "get_events")
        else [
            {
                "stage": job.stage.value,
                "agent_id": None,
                "message": job.message,
                "created_at": job.updated_at.isoformat(),
            }
        ]
    )
    statuses = _agent_statuses(job, events)
    live_outputs = {
        str(event["agent_id"]): event.get("output")
        for event in events
        if event.get("agent_id") and event.get("output") is not None
    }
    return {
        "job_id": job_id,
        "stage": job.stage.value,
        "progress": job.progress,
        "agents": [
            {
                "id": agent_id,
                "name": name,
                "branch": branch,
                "status": statuses[agent_id],
                "logs": [
                    event
                    for event in events
                    if event.get("agent_id") in {None, agent_id}
                ][-8:],
                "output": outputs.get(agent_id) or live_outputs.get(agent_id),
            }
            for agent_id, name, branch in AGENT_DEFINITIONS
        ],
    }


@router.get("/learning/jobs/{job_id}/rag")
def get_learning_rag(job_id: str, request: Request):
    result = _require_result(_service(request), job_id)
    return {
        "job_id": job_id,
        "items": (result.get("text_stage") or {}).get("rag_context", []),
    }


@router.get("/learning/jobs/{job_id}/text")
def get_learning_text(job_id: str, request: Request):
    result = _require_result(_service(request), job_id)
    if "text_stage" in result:
        return {
            "job_id": job_id,
            "text_stage": result["text_stage"],
            "text_review": result.get("text_review"),
        }
    return {"job_id": job_id, "poem": result.get("poem")}


@router.get("/learning/jobs/{job_id}/image-result")
def get_learning_image_result(job_id: str, request: Request):
    result = _require_result(_service(request), job_id)
    return {
        "job_id": job_id,
        "image": result.get("image"),
        "prompt_snapshot": result.get("prompt_snapshot"),
        "vision_review": result.get("vision_review"),
        "correction_history": result.get("correction_history", []),
    }


@router.get("/learning/jobs/{job_id}/reviews")
def get_learning_reviews(job_id: str, request: Request):
    result = _require_result(_service(request), job_id)
    return {
        "job_id": job_id,
        "text_review": result.get("text_review"),
        "vision_review": result.get("vision_review"),
        "final_decision": (
            result.get("final_decision") or result.get("final_review")
        ),
    }


@router.get("/learning/jobs/{job_id}/quiz")
def get_learning_quiz(job_id: str, request: Request):
    result = _require_result(_service(request), job_id)
    if "text_stage" in result:
        quiz = (
            result["text_stage"]["agent_outputs"].get("quiz")
        )
    else:
        quiz = result.get("quiz")
    return {"job_id": job_id, "quiz": quiz}


@router.get("/learning/jobs/{job_id}/report")
def get_learning_report(job_id: str, request: Request):
    service = _service(request)
    _require_job(service, job_id)
    report = service.get_report(job_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="learning report is not ready",
        )
    if hasattr(report, "model_dump"):
        return report.model_dump(mode="json")
    return report


@router.post("/learning/jobs/{job_id}/feedback")
def submit_teacher_feedback(
    job_id: str,
    payload: TeacherFeedbackRequest,
    request: Request,
):
    service = _service(request)
    job = _require_job(service, job_id)
    if job.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="teacher feedback requires a teacher job",
        )
    if job.stage != LearningStage.COMPLETED or service.get_result(job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="learning result is not ready",
        )
    if not hasattr(service, "apply_feedback"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="teacher feedback is unavailable in dev mode",
        )
    try:
        return service.apply_feedback(
            job_id,
            target_module=payload.target_module,
            feedback=payload.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/learning/jobs/{job_id}/package.zip")
def get_teacher_package(job_id: str, request: Request):
    service = _service(request)
    job = _require_job(service, job_id)
    if job.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="teacher package requires a teacher job",
        )
    if not hasattr(service, "build_teacher_package"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="teacher package is unavailable in dev mode",
        )
    try:
        content = service.build_teacher_package(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="poetry-edu-{job_id}.zip"'
            )
        },
    )


@router.post(
    "/learning/jobs/{job_id}/quiz",
    response_model=None,
)
def submit_quiz(
    job_id: str, payload: QuizSubmission, request: Request
):
    service = _service(request)
    job = _require_job(service, job_id)
    if job.stage != LearningStage.COMPLETED or service.get_result(job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="quiz is not ready",
        )
    try:
        return service.submit_quiz(job_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/image")
def get_image(request: Request, path: str = Query(...)):
    output_root = request.app.state.settings.output_dir.expanduser().resolve()
    image = Path(path).expanduser().resolve()
    if image != output_root and output_root not in image.parents:
        raise HTTPException(status_code=404, detail="image not found")
    if not image.is_file() or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(image)


# Compatibility aliases for early clients. New integrations should use
# /api/learning/jobs and the LearningStage contract.
@router.post(
    "/jobs",
    response_model=LegacyCreatedJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def legacy_create_learning_job(
    payload: LegacyCreateJobRequest, request: Request
) -> LegacyCreatedJob:
    service = _service(request)
    if service.run_mode != "dev":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="legacy jobs are available only in dev mode",
        )
    job = service.create_job("jing-ye-si")
    return LegacyCreatedJob(
        job_id=job.job_id,
        status=LEGACY_STAGE_MAP[job.stage],
        created_at=job.created_at,
    )


@router.get("/jobs/{job_id}", response_model=LegacyJob)
def legacy_get_learning_job(job_id: str, request: Request) -> LegacyJob:
    job = _require_job(_service(request), job_id)
    return LegacyJob(
        job_id=job.job_id,
        status=LEGACY_STAGE_MAP[job.stage],
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
    )


@router.get(
    "/jobs/{job_id}/result",
    response_model=LegacyLearningResult,
)
def legacy_get_learning_result(
    job_id: str, request: Request
) -> LegacyLearningResult:
    service = _service(request)
    job = _require_job(service, job_id)
    result = service.get_result(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"result is not ready: {job.stage.value}",
        )
    poem = result.poem
    return LegacyLearningResult(
        job_id=job_id,
        title=poem.title,
        author=poem.author,
        summary="诗人由清冷月色联想到故乡，表达夜深羁旅中的思乡之情。",
        translation=poem.translation,
        appreciation=[
            "月光与白霜的联想营造清冷、安静的夜景。",
            "“举头”与“低头”连接望月和思乡，形成动作与情感的转折。",
        ],
        knowledge_points=poem.knowledge_points,
    )


@router.get("/jobs/{job_id}/quiz", response_model=LegacyQuiz)
def legacy_get_quiz(job_id: str, request: Request) -> LegacyQuiz:
    service = _service(request)
    job = _require_job(service, job_id)
    result = service.get_result(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"quiz is not ready: {job.stage.value}",
        )
    objective_answers = {
        "objective-1": ("李白", "李白是《静夜思》的作者。"),
        "objective-2": (
            "低头思故乡",
            "末句直接点明诗人低头思念故乡。",
        ),
    }
    questions = []
    for question in result.quiz:
        if question.kind != "objective":
            continue
        answer, explanation = objective_answers[question.question_id]
        questions.append(
            LegacyQuizQuestion(
                id=question.question_id,
                prompt=question.prompt,
                options=[option.text for option in question.options],
                answer=answer,
                explanation=explanation,
            )
        )
    return LegacyQuiz(job_id=job_id, questions=questions)
