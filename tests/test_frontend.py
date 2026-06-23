from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_source_entry_exists() -> None:
    index = ROOT / "frontend" / "static" / "index.html"
    assert index.is_file(), "缺少 frontend/static/index.html"

    content = index.read_text(encoding="utf-8").lower()
    assert "<html" in content
    assert "诗" in content
    assert "/api/learning/jobs" in content, "前端入口应连接 dev jobs API"
    assert "styles.css?v=" in content
    assert "app.js?v=" in content

    script = (ROOT / "frontend" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "student_profile" in script
    assert "/api/image?path=" in script
    assert "不会用 dev 结果替代" in script
    assert 'health.run_mode' in script
    assert '"dev", "gpu"' in script
    assert "本地模型通常需要 3～6 分钟" in script
    assert "stageCardIndex" in script
    assert 'state.textContent = "执行失败"' in script
    assert ".card-heading b.dev" in (
        ROOT / "frontend" / "static" / "styles.css"
    ).read_text(encoding="utf-8")
    assert ".card-heading b.gpu" in (
        ROOT / "frontend" / "static" / "styles.css"
    ).read_text(encoding="utf-8")


def test_frontend_implements_live_jobs_and_teacher_feedback() -> None:
    index = (ROOT / "frontend" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")

    assert "new EventSource" in script
    assert "/events/stream" in script
    assert 'addEventListener("workflow_event"' in script
    assert "startPolling" in script
    assert "?role=${encodeURIComponent(role)}&limit=${limit}&offset=${offset}" in script
    assert "/feedback" in script
    assert "await requestJson(API.job(jobId))" in script
    assert "startSse(state.generationToken)" in script
    assert "target_module" in script
    assert "teaching_key_difficulties" in script
    assert "teacher-image-tech\").textContent = prettyJson({ correction_history" not in script
    assert "package.zip" in script
    assert "下载资源包 ZIP" in index
    assert 'id="feedback-dialog"' in index
    assert 'id="view-history"' in index


def test_frontend_has_role_specific_results_and_black_font_stack() -> None:
    index = (ROOT / "frontend" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "static" / "styles.css").read_text(encoding="utf-8")

    for label in ("教学目标", "教学重难点", "课堂活动", "学生测评题预览"):
        assert label in index
    for label in ("原诗", "字词卡", "情感标签", "看图小任务"):
        assert label in index or label in script
    for label in ("掌握较好", "需要加强", "推荐复习"):
        assert label in index
    assert 'id="view-report"' in index
    assert "answer-explanation" in script
    assert "智能点评" in script
    for forbidden in ("STSong", "SimSun", "宋体", "KaiTi", "STKaiti"):
        assert forbidden not in styles
    assert "@media (max-width: 900px)" in styles
    assert ".result-grid { display: grid; grid-template-columns: .82fr 1.18fr; align-items: start;" in styles
    assert "aspect-ratio: 1 / 1; align-self: start;" in styles
    assert ".student-study { display: grid; grid-template-columns: .8fr 1.2fr; align-items: start;" in styles


def test_frontend_is_served_at_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "诗" in response.text
