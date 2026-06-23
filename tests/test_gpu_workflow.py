from __future__ import annotations

import json
from types import SimpleNamespace

from backend.agents import STANDARD_PROMPT_SCHEMA
from backend.generation import KolorsResult
from backend.orchestration.gpu_workflow import (
    TEXT_REVIEW_SCHEMA,
    VISION_SCHEMA,
    GpuLearningWorkflow,
    build_final_decision,
    normalize_text_review,
    normalize_vision_review,
    unavailable_vision_review,
    vision_review_from_text,
)


def _vision(**overrides):
    detected = {
        "one_poet": True,
        "moon": True,
        "moonlight_on_ground": True,
        "ancient_bed": True,
        "modern_objects": False,
        "snow_or_real_frost": False,
        "artificial_light": False,
    }
    detected.update(overrides)
    return {
        "image_summary": "月夜室内",
        "person_count": 1,
        "key_elements_detected": detected,
        "missing_elements": [],
        "possible_errors": [],
        "pass": True,
        "revision_advice": [],
    }


def test_review_schemas_have_separate_responsibilities():
    assert "revision_advice" in VISION_SCHEMA["required"]
    assert "teaching_issues" in TEXT_REVIEW_SCHEMA["required"]
    assert "image_issues" not in TEXT_REVIEW_SCHEMA["properties"]
    assert "scene" in STANDARD_PROMPT_SCHEMA["required"]


def test_vision_failure_produces_prompt_revision_advice():
    result = normalize_vision_review(
        _vision(one_poet=False, artificial_light=True)
    )
    assert result["pass"] is False
    assert "画面未确认只出现一名诗人" in result["possible_errors"]
    assert any("一名古代诗人" in item for item in result["revision_advice"])
    assert any("人工光" in item for item in result["revision_advice"])


def test_vision_review_discards_contradictory_model_advice():
    output = _vision(one_poet=False)
    output["possible_errors"] = ["没有灯笼"]
    output["revision_advice"] = ["添加灯笼"]
    result = normalize_vision_review(output)
    assert "添加灯笼" not in result["revision_advice"]
    assert "没有灯笼" not in result["possible_errors"]


def test_clean_vision_result_passes():
    assert normalize_vision_review(_vision())["pass"] is True


def test_unavailable_revised_vision_review_fails_closed():
    result = unavailable_vision_review("审核格式不可用")

    assert result["pass"] is False
    assert result["key_elements_detected"]["one_poet"] is False
    assert "审核结果不可用" in result["possible_errors"][0]


def test_compact_vision_text_is_parsed_deterministically():
    result = vision_review_from_text(
        "人物数量=1；单一古代诗人=是；明月=有；床前地面月光=有；"
        "古代床榻=无；现代物品=无；真实冰霜或雪=无；人工照明=无；"
        "画面概述=诗人坐在窗前望月；问题=缺少古代床榻；"
        "修改建议=加入结构清晰的木质床榻"
    )

    assert result["person_count"] == 1
    assert result["key_elements_detected"]["one_poet"] is True
    assert result["key_elements_detected"]["ancient_bed"] is False
    assert result["pass"] is False
    assert "画面缺少明确的古代床榻" in result["possible_errors"]
    assert result["observation_text"].startswith("人物数量=1")


def test_incomplete_vision_text_fails_closed_without_exception():
    result = vision_review_from_text("人物数量=1；画面概述=诗人坐在窗边")

    assert result["pass"] is False
    assert "视觉观察报告字段不完整" in result["possible_errors"]


def test_ambiguous_vision_choice_is_not_treated_as_positive():
    result = vision_review_from_text(
        "人物数量=1；单一古代诗人=是/否；明月=有；床前地面月光=有；"
        "古代床榻=有；现代物品=无；真实冰霜或雪=无；人工照明=无；"
        "画面概述=诗人坐在床边；问题=无；修改建议=无"
    )

    assert result["pass"] is False
    assert "视觉判断值无效：单一古代诗人" in result["possible_errors"]


def test_text_review_pass_is_derived_from_text_issues():
    review = normalize_text_review(
        {
            "reviewer": "deepseek",
            "review_result": "pass",
            "pass": True,
            "knowledge_issues": [],
            "quiz_issues": ["题目偏离目标"],
            "teaching_issues": [],
            "required_actions": ["修改题目"],
            "review_summary": "需修改",
            "fallback_used": False,
        }
    )
    assert review["pass"] is False
    assert review["review_result"] == "needs_revision"


def test_final_gate_requires_text_and_vision_to_pass():
    decision = build_final_decision(
        text_review={"pass": True, "fallback_used": False},
        vision_review={"pass": False},
    )
    assert decision == {
        "pass": False,
        "text_pass": True,
        "vision_pass": False,
        "fallback_used": False,
        "failed_parts": ["vision"],
    }


def test_deepseek_text_input_excludes_image_prompt_and_vision():
    review_input = GpuLearningWorkflow._text_review_input(
        poem="床前明月光",
        student_profile={"grade": "小学"},
        text_result={
            "rag_context": [{"title": "静夜思"}],
            "agent_outputs": {
                "learning_resources": {
                    "layered_explanations": {"basic": "解释"},
                    "standard_prompt_json": {"scene": "月夜"},
                    "image_prompt": {"zh_prompt": "月夜"},
                    "quality_prompts": {"kolors": {"zh_prompt": "月夜"}},
                },
                "quiz": {"objective_questions": []},
                "local_review": {"pass": True},
            },
        },
    )
    assert review_input["scope"] == "text_only"
    assert "image_prompt" not in review_input["text_resources"]["learning_resources"]
    assert "standard_prompt_json" not in review_input[
        "text_resources"
    ]["learning_resources"]
    assert "quality_prompts" not in review_input[
        "text_resources"
    ]["learning_resources"]
    assert "local_review" not in review_input["text_resources"]
    assert "vision_description" not in review_input


def test_deepseek_feedback_is_sent_verbatim_to_resource_agent(tmp_path):
    class RevisionQwen:
        def __init__(self):
            self.request = None

        def run_text(self, request):
            self.request = request
            return SimpleNamespace(
                output={
                    "poem_analysis": {},
                    "learning_resources": {},
                    "quiz": {},
                },
                metrics={"mode": "fake"},
            )

    qwen = RevisionQwen()
    workflow = GpuLearningWorkflow(
        db_path=str(tmp_path / "knowledge.db"),
        output_root=str(tmp_path),
        qwen_client=qwen,
        kolors_client=object(),
        vision_client=object(),
        deepseek_client=object(),
        prompt_compiler=object(),
    )
    action = "修正客观题选项，确保“明月光”表示月光而非月亮。"
    revision = workflow._rewrite_text_outputs_from_review(
        poem="床前明月光",
        student_profile={"grade": "四年级"},
        text_result={
            "rag_context": [{"title": "静夜思"}],
            "agent_outputs": {
                "poem_analysis": {"plain_translation": "月光照在床前"},
                "learning_resources": {
                    "classroom_intro": "看图导入",
                    "standard_prompt_json": {"scene": "月夜"},
                    "image_prompt": {"zh_prompt": "月夜"},
                    "quality_prompts": {"kolors": {"zh_prompt": "月夜"}},
                },
                "quiz": {"objective_questions": [], "subjective_questions": []},
            },
        },
        text_review={
            "knowledge_issues": [],
            "quiz_issues": ["选项表述不准确"],
            "teaching_issues": [],
            "required_actions": [action],
            "review_summary": "需要修改",
        },
    )
    agent_input = json.loads(qwen.request.user_prompt)
    assert agent_input["deepseek_review"]["required_actions"] == [action]
    assert agent_input["previous_output"]["learning_resources"] == {
        "classroom_intro": "看图导入"
    }
    assert "不得修改任何图片" in qwen.request.system_prompt
    assert revision["metrics"] == {"mode": "fake"}


def test_workflow_uses_vl_feedback_to_rewrite_prompt_once(
    monkeypatch,
    tmp_path,
):
    text_result = {
        "rag_context": [{"title": "静夜思"}],
        "agent_outputs": {
            "learning_resources": {
                "layered_explanations": {"basic": "解释"},
                "standard_prompt_json": {
                    "poem": "床前明月光，疑是地上霜",
                    "explanation": "月光照在床前",
                    "scene": "古代中国室内夜晚",
                    "subject": "一名唐代诗人",
                    "action": "坐在床榻旁低头沉思",
                    "composition": "中景单人构图",
                    "visual_focus": ["明月", "床前月光"],
                    "light": "冷白月光照亮床前",
                    "emotion": "安静、思乡",
                    "style": "水墨写意，古风，冷色调",
                    "avoid": ["现代物品"],
                    "composition_constraints": ["一名诗人"],
                },
            },
            "quiz": {"objective_questions": [], "subjective_questions": []},
            "local_review": {"pass": True},
        },
    }

    class FakeTextStageRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            return text_result

    class FakeDeepSeek:
        def __init__(self):
            self.input = None

        def review(self, *, review_input, output_schema):
            self.input = review_input
            return {
                "reviewer": "deepseek",
                "review_result": "pass",
                "pass": True,
                "knowledge_issues": [],
                "quiz_issues": [],
                "teaching_issues": [],
                "required_actions": [],
                "review_summary": "通过",
                "fallback_used": False,
            }

    class FakeQwen:
        def __init__(self):
            self.requests = []

        def run_text(self, request):
            self.requests.append(request)
            return SimpleNamespace(
                output={
                    "poem": "床前明月光，疑是地上霜",
                    "explanation": "月光照在床前",
                    "scene": "古代中国室内夜晚",
                    "subject": "一名唐代诗人",
                    "action": "坐在古代木质床榻旁低头沉思",
                    "composition": "中景单人室内构图",
                    "visual_focus": ["诗人", "古代木质床榻", "明月"],
                    "light": "冷白月光照亮床前",
                    "emotion": "安静、思乡",
                    "style": "水墨写意，古风，冷色调",
                    "avoid": ["现代物品", "多人"],
                    "composition_constraints": ["只出现一名诗人"],
                },
                metrics={"mode": "fake"},
            )

    class FakeKolors:
        def __init__(self):
            self.requests = []

        def generate(self, request):
            self.requests.append(request)
            index = len(self.requests)
            return KolorsResult(
                image_path=str(tmp_path / f"{index}.png"),
                metadata_path=str(tmp_path / f"{index}.json"),
                seed=request.seed,
                metrics={"mode": "fake"},
            )

    class FakeVision:
        def __init__(self):
            self.calls = 0

        def review(self, request):
            self.calls += 1
            output = (
                _vision(one_poet=False, ancient_bed=False)
                if self.calls == 1
                else _vision()
            )
            return SimpleNamespace(output=output, metrics={"mode": "fake"})

    monkeypatch.setattr(
        "backend.orchestration.gpu_workflow.TextStageRunner",
        FakeTextStageRunner,
    )
    deepseek = FakeDeepSeek()
    qwen = FakeQwen()
    kolors = FakeKolors()
    workflow = GpuLearningWorkflow(
        db_path=str(tmp_path / "knowledge.db"),
        output_root=str(tmp_path),
        qwen_client=qwen,
        kolors_client=kolors,
        vision_client=FakeVision(),
        deepseek_client=deepseek,
    )

    result = workflow.run(
        poem="床前明月光",
        student_profile={"grade": "小学"},
        job_id="job_test",
    )

    assert deepseek.input["scope"] == "text_only"
    assert "vision_description" not in deepseek.input
    assert len(qwen.requests) == 1
    assert "revision_advice" in qwen.requests[0].user_prompt
    assert "qwen_vl_observation_text" in qwen.requests[0].user_prompt
    assert len(kolors.requests) == 2
    assert not kolors.requests[1].prompt.startswith("{")
    assert "主体：" not in kolors.requests[1].prompt
    assert "古代木质床榻" in kolors.requests[1].prompt
    assert 120 <= len(kolors.requests[1].prompt) <= 220
    assert "无人" in kolors.requests[1].negative_prompt
    assert "纯风景" in kolors.requests[1].negative_prompt
    assert result["final_decision"]["pass"] is True
    history = result["correction_history"][0]
    assert history["qwen_standard_prompt_revision"]["output"]["scene"] == (
        "古代中国室内夜晚"
    )
    assert history["after_kolors_prompt"]["zh_prompt"] == (
        kolors.requests[1].prompt
    )
    assert result["prompt_snapshot"]["final_kolors_prompt"]["zh_prompt"] == (
        kolors.requests[1].prompt
    )
