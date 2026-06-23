from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

from backend.model_clients import QwenAwqClient, QwenTextRequest
from backend.rag import search_poems
from .kolors_prompt_compiler import STANDARD_PROMPT_SCHEMA


STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
QUESTION_COMMON = {
    "type": "object",
    "required": [
        "id",
        "target_skill",
        "difficulty",
        "question",
        "reference_answer",
        "explanation",
    ],
    "properties": {
        "id": {"type": "string"},
        "target_skill": {"type": "string"},
        "difficulty": {"type": "string"},
        "question": {"type": "string"},
        "reference_answer": {"type": "string"},
        "explanation": {"type": "string"},
    },
}


TEXT_STAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "student_diagnosis",
        "poem_analysis",
        "learning_resources",
        "quiz",
        "local_review",
    ],
    "additionalProperties": False,
    "properties": {
        "student_diagnosis": {
            "type": "object",
            "required": [
                "student_level",
                "diagnosis_summary",
                "mastered_points",
                "weak_points",
                "recommended_difficulty",
                "resource_strategy",
                "confidence",
            ],
            "properties": {
                "student_level": {
                    "type": "string",
                    "enum": ["basic", "medium", "advanced"],
                },
                "diagnosis_summary": {"type": "string"},
                "mastered_points": STRING_ARRAY,
                "weak_points": STRING_ARRAY,
                "recommended_difficulty": {"type": "string"},
                "resource_strategy": {
                    "type": "object",
                    "required": [
                        "explanation_depth",
                        "question_difficulty",
                        "visual_support",
                        "avoid",
                    ],
                    "properties": {
                        "explanation_depth": {"type": "string"},
                        "question_difficulty": {"type": "string"},
                        "visual_support": {"type": "boolean"},
                        "avoid": STRING_ARRAY,
                    },
                },
                "confidence": {"type": "number"},
            },
        },
        "poem_analysis": {
            "type": "object",
            "required": [
                "plain_translation",
                "word_notes",
                "imagery",
                "emotion",
                "emotion_evidence",
                "techniques",
                "teaching_focus",
                "risk_notes",
            ],
            "properties": {
                "plain_translation": {"type": "string"},
                "word_notes": STRING_ARRAY,
                "imagery": STRING_ARRAY,
                "emotion": {"type": "string"},
                "emotion_evidence": STRING_ARRAY,
                "techniques": STRING_ARRAY,
                "teaching_focus": STRING_ARRAY,
                "risk_notes": STRING_ARRAY,
            },
        },
        "learning_resources": {
            "type": "object",
            "required": [
                "layered_explanations",
                "classroom_intro",
                "guided_questions",
                "teaching_goals",
                "teaching_key_difficulties",
                "classroom_activities",
                "standard_prompt_json",
            ],
            "properties": {
                "layered_explanations": {
                    "type": "object",
                    "required": ["basic", "medium", "advanced"],
                    "properties": {
                        "basic": {"type": "string"},
                        "medium": {"type": "string"},
                        "advanced": {"type": "string"},
                    },
                },
                "classroom_intro": {"type": "string"},
                "teaching_goals": STRING_ARRAY,
                "teaching_key_difficulties": {
                    "type": "object",
                    "required": ["key_points", "difficulties"],
                    "properties": {
                        "key_points": STRING_ARRAY,
                        "difficulties": STRING_ARRAY,
                    },
                },
                "classroom_activities": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "required": ["name", "procedure", "purpose"],
                        "properties": {
                            "name": {"type": "string"},
                            "procedure": STRING_ARRAY,
                            "purpose": {"type": "string"},
                        },
                    },
                },
                "guided_questions": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 4,
                    "items": {"type": "string"},
                },
                "standard_prompt_json": STANDARD_PROMPT_SCHEMA,
            },
        },
        "quiz": {
            "type": "object",
            "required": ["objective_questions", "subjective_questions"],
            "properties": {
                "objective_questions": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "target_skill",
                            "difficulty",
                            "question",
                            "options",
                            "answer",
                            "explanation",
                        ],
                        "properties": {
                            "id": {
                                "type": "string",
                                "enum": ["obj_1", "obj_2"],
                            },
                            "target_skill": {"type": "string"},
                            "difficulty": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "object",
                                "required": ["A", "B", "C", "D"],
                                "additionalProperties": False,
                                "properties": {
                                    "A": {"type": "string"},
                                    "B": {"type": "string"},
                                    "C": {"type": "string"},
                                    "D": {"type": "string"},
                                },
                            },
                            "answer": {
                                "type": "string",
                                "enum": ["A", "B", "C", "D"],
                            },
                            "explanation": {"type": "string"},
                        },
                    },
                },
                "subjective_questions": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "target_skill",
                            "difficulty",
                            "question",
                            "reference_answer",
                            "rubric",
                            "total_score",
                        ],
                        "properties": {
                            "id": {
                                "type": "string",
                                "enum": ["subj_1", "subj_2"],
                            },
                            "target_skill": {"type": "string"},
                            "difficulty": {"type": "string"},
                            "question": {"type": "string"},
                            "reference_answer": {"type": "string"},
                            "rubric": {
                                "type": "array",
                                "minItems": 2,
                                "items": {
                                    "type": "object",
                                    "required": ["point", "score"],
                                    "properties": {
                                        "point": {"type": "string"},
                                        "score": {"type": "integer"},
                                    },
                                },
                            },
                            "total_score": {"type": "integer"},
                        },
                    },
                },
            },
        },
        "local_review": {
            "type": "object",
            "required": ["pass", "issues", "risk_level", "review_summary"],
            "properties": {
                "pass": {"type": "boolean"},
                "issues": STRING_ARRAY,
                "risk_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
                "review_summary": {"type": "string"},
            },
        },
    },
}


def build_text_stage_request(
    *,
    poem: str,
    student_profile: Mapping[str, Any],
    rag_context: list[Mapping[str, Any]],
) -> QwenTextRequest:
    context = json.dumps(rag_context, ensure_ascii=False, separators=(",", ":"))
    profile = json.dumps(student_profile, ensure_ascii=False, separators=(",", ":"))
    audience_role = str(
        student_profile.get("audience_role") or "student"
    ).lower()
    custom_requirements = str(
        student_profile.get("custom_requirements") or ""
    ).strip()
    if audience_role == "teacher":
        audience_instruction = (
            "当前使用者是教师。learning_resources 必须面向真实备课："
            "classroom_intro 写成教师可直接使用的课堂导入语；"
            "layered_explanations 分别给出基础讲解、课堂追问和进阶点拨；"
            "teaching_goals、teaching_key_difficulties 和 classroom_activities "
            "分别给出可评价目标、教学重点难点和可执行课堂活动；"
            "guided_questions 应形成可在课堂实施的问题链，并体现差异化教学。"
            "语言要专业、可执行，避免把内容写成对学生的系统操作说明。"
        )
    else:
        audience_instruction = (
            "当前使用者是学生。learning_resources 必须面向自主学习："
            "classroom_intro 改写为亲切的自学导语；layered_explanations "
            "使用学生能直接读懂的表达，并给出由浅入深的学习步骤；"
            "teaching_goals 写成学习目标，teaching_key_difficulties 写成"
            "学习重点与难点，classroom_activities 改写为可独立完成的学习活动；"
            "guided_questions 应提供思考方向但不能直接泄露答案。"
            "不要出现教案、授课流程、教师话术或课堂管理指令。"
        )
    custom_instruction = (
        f"用户补充要求：{custom_requirements}。"
        if custom_requirements
        else ""
    )
    return QwenTextRequest(
        task_name="complete_text_stage",
        system_prompt=(
            "你是诗境智学的文本阶段总协调器。你要分别扮演学情诊断、"
            "古诗解析、学习资源生成、题目生成和本地初审五个角色。"
            "只使用给定古诗、学生画像和本地知识库证据；不确定的作者背景不要编造。"
            "emotion_evidence 必须逐字引用原诗，不得写成白话改写。"
        ),
        user_prompt=(
            f"古诗：{poem}\n学生画像：{profile}\n本地知识库：{context}\n\n"
            f"{audience_instruction}{custom_instruction}"
            "请生成一套真正适合当前使用者和学生画像的学习资源。必须固定生成 2 道客观题和"
            " 2 道主观题；客观题答案唯一，主观题必须带评分 rubric。"
            "题目 ID 必须依次使用 obj_1、obj_2、subj_1、subj_2，且至少三题"
            "直接针对学生薄弱点，不能主要考作者常识。standard_prompt_json 必须"
            "输出结构化画面信息，不要提前拼接 Kolors 自然语言 Prompt；scene、"
            "subject、action、composition、visual_focus、light、emotion、style、"
            "avoid 和 composition_constraints 必须具体。明确人物数量、古代身份、"
            "床榻、月亮、床前月光、构图和禁止的现代元素。“霜”只能表示冷白月光"
            "形成的视觉联想，不得生成真实冰霜。单幅图只选择一个人物动作，禁止"
            "要求同一人物同时抬头和低头。最后进行一次本地初审；若引用"
            "不是原诗、题目 ID 重复、题目偏离薄弱点或图像硬约束不完整，pass 必须为 false。"
        ),
        output_schema=TEXT_STAGE_SCHEMA,
        max_input_tokens=6144,
        max_new_tokens=2048,
        temperature=0.15,
    )


def apply_semantic_guardrails(
    *,
    poem: str,
    output: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    guarded = deepcopy(dict(output))
    corrections: list[str] = []
    image_prompt = guarded["learning_resources"]["standard_prompt_json"]
    combined = " ".join(
        [
            str(image_prompt.get("action") or ""),
            *[str(item) for item in image_prompt.get("composition_constraints") or []],
        ]
    )
    if (
        "举头望明月" in poem
        and "低头思故乡" in poem
        and "抬头" in combined
        and "低头" in combined
    ):
        image_prompt["scene"] = "古代中国室内夜晚，木格窗外可见明月"
        image_prompt["subject"] = "一名唐代诗人"
        image_prompt["action"] = "侧身坐在古代木质床榻旁，低头沉思"
        image_prompt["composition"] = (
            "中景单人构图，诗人、古代床榻、窗外明月和床前地面同时清晰可见"
        )
        image_prompt["visual_focus"] = [
            "一名唐代诗人",
            "古代木质床榻",
            "窗外明月",
            "床前冷白月光光斑",
        ]
        image_prompt["light"] = (
            "冷白月光穿过木格窗，铺在床前地面形成如霜的明亮光斑"
        )
        image_prompt["emotion"] = "安静、清冷、孤独、思乡"
        image_prompt["style"] = "水墨写意，古风，中国画意境，留白充足，冷色调"
        image_prompt["composition_constraints"] = [
            "只出现一名唐代诗人",
            "诗人侧身坐在床榻旁并低头沉思",
            "窗外明月清晰可见",
            "冷白月光铺在床前地面并形成如霜光斑",
            "地面不得出现真实冰霜",
            "不得出现灯笼、电灯、现代家具、现代建筑或文字水印",
        ]
        corrections.append("消除单幅图中人物同时抬头和低头的动作冲突")

    if "疑是地上霜" in poem:
        image_prompt["poem"] = poem
        image_prompt["scene"] = "古代中国室内夜晚，木格窗外可见一轮明月"
        image_prompt["subject"] = "一名独处的古代诗人"
        image_prompt["action"] = (
            "侧身坐在简朴的古代木质床榻旁，低头望向床前月光"
        )
        image_prompt["composition"] = (
            "中景单人室内构图，诗人、古代木质床榻、木格窗、"
            "窗外明月和床前地面同时清晰可见"
        )
        image_prompt["visual_focus"] = [
            "一名古代诗人",
            "结构清晰的古代木质床榻",
            "窗外明月",
            "床前地面的冷白月光光斑",
        ]
        image_prompt["light"] = (
            "清冷月光从木格窗外照入，在床前地面形成明亮的白色光斑"
        )
        image_prompt["emotion"] = "安静、孤独、静谧、思乡"
        image_prompt["style"] = (
            "水墨写意，古风，中国画意境，留白充足，冷色调"
        )
        image_prompt["composition_constraints"] = [
            "画面中只有一位古代诗人",
            "诗人位于古代木质床榻旁",
            "月色像霜但地面没有真实冰霜",
            "地面有明确的冷白月光光斑",
        ]
        avoid = list(image_prompt.get("avoid") or [])
        additions = [
            "真实冰霜",
            "雪花",
            "飘雪",
            "白色漂浮颗粒",
            "灯笼",
            "油灯",
            "烛台",
            "暖黄色室内光",
            "人工光源",
        ]
        missing = [item for item in additions if item not in avoid]
        if missing:
            image_prompt["avoid"] = [*avoid, *missing]
        corrections.append("标准化床前月光场景并补充负面约束")

    evidence = guarded["poem_analysis"].get("emotion_evidence") or []
    invalid_evidence = [
        item
        for item in evidence
        if str(item).strip("。！？；， ") not in poem
    ]
    if invalid_evidence:
        guarded["local_review"]["pass"] = False
        guarded["local_review"]["risk_level"] = "medium"
        guarded["local_review"]["issues"].append("情感证据不是原诗逐字引用")
        corrections.append("标记非原诗情感证据，等待修正")

    return guarded, corrections


class TextStageRunner:
    def __init__(
        self,
        *,
        db_path: str,
        client: QwenAwqClient | None = None,
    ) -> None:
        self.db_path = db_path
        self.client = client or QwenAwqClient()

    def run(
        self,
        *,
        poem: str,
        student_profile: Mapping[str, Any],
    ) -> dict[str, Any]:
        rag_context = search_poems(self.db_path, poem, limit=3)
        request = build_text_stage_request(
            poem=poem,
            student_profile=student_profile,
            rag_context=rag_context,
        )
        result = self.client.run_text(request)
        guarded_output, corrections = apply_semantic_guardrails(
            poem=poem,
            output=result.output,
        )
        return {
            "rag_context": rag_context,
            "agent_outputs": guarded_output,
            "guardrail_corrections": corrections,
            "model_metrics": dict(result.metrics),
        }
