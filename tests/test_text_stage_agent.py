from __future__ import annotations

from backend.agents import TEXT_STAGE_SCHEMA, build_text_stage_request
from backend.agents.text_stage import apply_semantic_guardrails
from backend.utils import validate_json_schema


def test_text_stage_request_contains_profile_rag_and_fixed_quiz_contract():
    request = build_text_stage_request(
        poem="床前明月光，疑是地上霜。",
        student_profile={"grade": "七年级", "level": "basic"},
        rag_context=[{"poem": {"title": "静夜思"}}],
    )
    assert "七年级" in request.user_prompt
    assert "静夜思" in request.user_prompt
    objective = TEXT_STAGE_SCHEMA["properties"]["quiz"]["properties"][
        "objective_questions"
    ]
    subjective = TEXT_STAGE_SCHEMA["properties"]["quiz"]["properties"][
        "subjective_questions"
    ]
    assert objective["minItems"] == objective["maxItems"] == 2
    assert subjective["minItems"] == subjective["maxItems"] == 2
    assert objective["items"]["properties"]["id"]["enum"] == ["obj_1", "obj_2"]
    assert subjective["items"]["properties"]["id"]["enum"] == ["subj_1", "subj_2"]


def test_text_stage_prompt_changes_with_teacher_and_student_role():
    teacher = build_text_stage_request(
        poem="床前明月光",
        student_profile={
            "grade": "四年级",
            "level": "medium",
            "audience_role": "teacher",
            "custom_requirements": "增加小组讨论",
        },
        rag_context=[],
    )
    student = build_text_stage_request(
        poem="床前明月光",
        student_profile={
            "grade": "四年级",
            "level": "medium",
            "audience_role": "student",
        },
        rag_context=[],
    )

    assert "当前使用者是教师" in teacher.user_prompt
    assert "增加小组讨论" in teacher.user_prompt
    assert "当前使用者是学生" in student.user_prompt
    assert "不要出现教案" in student.user_prompt


def test_text_stage_schema_rejects_wrong_quiz_count():
    value = {
        "student_diagnosis": {
            "student_level": "basic",
            "diagnosis_summary": "基础薄弱",
            "mastered_points": [],
            "weak_points": ["imagery_analysis"],
            "recommended_difficulty": "medium_low",
            "resource_strategy": {
                "explanation_depth": "guided",
                "question_difficulty": "basic",
                "visual_support": True,
                "avoid": [],
            },
            "confidence": 0.8,
        },
        "poem_analysis": {
            "plain_translation": "译文",
            "word_notes": [],
            "imagery": ["月"],
            "emotion": "思乡",
            "emotion_evidence": ["低头思故乡"],
            "techniques": ["借景抒情"],
            "teaching_focus": [],
            "risk_notes": [],
        },
        "learning_resources": {
            "layered_explanations": {
                "basic": "基础",
                "medium": "中等",
                "advanced": "进阶",
            },
            "classroom_intro": "导入",
            "guided_questions": ["一", "二", "三"],
            "teaching_goals": ["理解诗意"],
            "teaching_key_difficulties": {
                "key_points": ["月亮意象"],
                "difficulties": ["体会思乡情感"],
            },
            "classroom_activities": [
                {
                    "name": "朗读",
                    "procedure": ["齐读全诗"],
                    "purpose": "熟悉诗句",
                },
                {
                    "name": "品读",
                    "procedure": ["圈画意象"],
                    "purpose": "理解情感",
                },
            ],
            "standard_prompt_json": {
                "poem": "床前明月光",
                "explanation": "月光照在床前",
                "scene": "古代室内夜晚",
                "subject": "一名诗人",
                "action": "坐在床榻旁",
                "composition": "中景单人构图",
                "visual_focus": ["床榻", "明月"],
                "light": "冷白月光照亮床前",
                "emotion": "安静、思乡",
                "style": "水墨写意",
                "avoid": ["现代物品"],
                "composition_constraints": [],
            },
        },
        "quiz": {
            "objective_questions": [],
            "subjective_questions": [],
        },
        "local_review": {
            "pass": False,
            "issues": ["题量错误"],
            "risk_level": "high",
            "review_summary": "未通过",
        },
    }
    try:
        validate_json_schema(value, TEXT_STAGE_SCHEMA)
    except ValueError as exc:
        assert "数组长度" in str(exc)
    else:
        raise AssertionError("错误题量不应通过 schema 校验")


def test_semantic_guardrail_repairs_conflicting_jingyesi_pose():
    output = {
        "learning_resources": {
            "standard_prompt_json": {
                "poem": "静夜思",
                "explanation": "月光引发思乡",
                "scene": "古代室内夜晚",
                "subject": "一名唐代诗人",
                "action": "诗人抬头望月，又低头沉思",
                "composition": "中景单人构图",
                "visual_focus": ["床榻", "明月"],
                "light": "冷白月光",
                "emotion": "思乡",
                "style": "水墨写意",
                "avoid": [],
                "composition_constraints": ["抬头望月", "低头沉思"],
            }
        },
        "poem_analysis": {"emotion_evidence": ["低头思故乡"]},
        "local_review": {
            "pass": True,
            "issues": [],
            "risk_level": "low",
        },
    }
    guarded, corrections = apply_semantic_guardrails(
        poem="床前明月光，疑是地上霜。举头望明月，低头思故乡。",
        output=output,
    )
    prompt = guarded["learning_resources"]["standard_prompt_json"]
    assert "古代木质床榻旁" in prompt["action"]
    assert not ("抬头" in prompt["action"] and "低头" in prompt["action"])
    assert "雪花" in prompt["avoid"]
    assert prompt["scene"].startswith("古代中国室内夜晚")
    assert "床前地面的冷白月光光斑" in prompt["visual_focus"]
    assert "地上的白霜" not in prompt["visual_focus"]
    assert corrections
