from __future__ import annotations

import json
import logging
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from backend.agents import (
    STANDARD_PROMPT_SCHEMA,
    TEXT_STAGE_SCHEMA,
    KolorsPromptCompiler,
    TextStageRunner,
)
from backend.generation import KolorsClient, KolorsRequest
from backend.model_clients import (
    DeepSeekClient,
    DeepSeekReviewError,
    QwenAwqClient,
    QwenTextRequest,
    QwenVisionClient,
    QwenVisionRequest,
)


VISION_SCHEMA = {
    "type": "object",
    "required": [
        "image_summary",
        "person_count",
        "key_elements_detected",
        "missing_elements",
        "possible_errors",
        "pass",
        "revision_advice",
    ],
    "properties": {
        "image_summary": {"type": "string"},
        "person_count": {"type": "integer"},
        "key_elements_detected": {
            "type": "object",
            "required": [
                "one_poet",
                "moon",
                "moonlight_on_ground",
                "ancient_bed",
                "modern_objects",
                "snow_or_real_frost",
                "artificial_light",
            ],
            "additionalProperties": False,
            "properties": {
                "one_poet": {"type": "boolean"},
                "moon": {"type": "boolean"},
                "moonlight_on_ground": {"type": "boolean"},
                "ancient_bed": {"type": "boolean"},
                "modern_objects": {"type": "boolean"},
                "snow_or_real_frost": {"type": "boolean"},
                "artificial_light": {"type": "boolean"},
            },
        },
        "missing_elements": {"type": "array", "items": {"type": "string"}},
        "possible_errors": {"type": "array", "items": {"type": "string"}},
        "pass": {"type": "boolean"},
        "revision_advice": {"type": "array", "items": {"type": "string"}},
    },
}


TEXT_REVIEW_SCHEMA = {
    "type": "object",
    "required": [
        "reviewer",
        "review_result",
        "pass",
        "knowledge_issues",
        "quiz_issues",
        "teaching_issues",
        "required_actions",
        "review_summary",
        "fallback_used",
    ],
    "additionalProperties": False,
    "properties": {
        "reviewer": {"type": "string"},
        "review_result": {
            "type": "string",
            "enum": [
                "pass",
                "needs_revision",
                "fallback_review",
            ],
        },
        "pass": {"type": "boolean"},
        "knowledge_issues": {"type": "array", "items": {"type": "string"}},
        "quiz_issues": {"type": "array", "items": {"type": "string"}},
        "teaching_issues": {"type": "array", "items": {"type": "string"}},
        "required_actions": {"type": "array", "items": {"type": "string"}},
        "review_summary": {"type": "string"},
        "fallback_used": {"type": "boolean"},
    },
}

TEXT_RESOURCE_REVISION_SCHEMA = {
    "type": "object",
    "required": ["poem_analysis", "learning_resources", "quiz"],
    "additionalProperties": False,
    "properties": {
        "poem_analysis": TEXT_STAGE_SCHEMA["properties"]["poem_analysis"],
        "learning_resources": {
            "type": "object",
            "required": [
                "layered_explanations",
                "classroom_intro",
                "guided_questions",
                "teaching_goals",
                "teaching_key_difficulties",
                "classroom_activities",
            ],
            "additionalProperties": False,
            "properties": {
                key: TEXT_STAGE_SCHEMA["properties"]["learning_resources"][
                    "properties"
                ][key]
                for key in (
                    "layered_explanations",
                    "classroom_intro",
                    "guided_questions",
                    "teaching_goals",
                    "teaching_key_difficulties",
                    "classroom_activities",
                )
            },
        },
        "quiz": TEXT_STAGE_SCHEMA["properties"]["quiz"],
    },
}

logger = logging.getLogger("uvicorn.error")

# Backward-compatible import name for existing callers.
REVIEW_SCHEMA = TEXT_REVIEW_SCHEMA


@dataclass(frozen=True)
class WorkflowEvent:
    stage: str
    message: str
    agent_id: str | None = None
    output: Mapping[str, Any] | None = None
    status: str | None = None


def normalize_vision_review(output: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(output)
    detected = normalized.get("key_elements_detected") or {}
    issues = []
    advice = []
    failures = []
    if detected.get("one_poet") is not True:
        failures.append(("画面未确认只出现一名诗人", "明确呈现且只呈现一名古代诗人"))
    if detected.get("moon") is not True:
        failures.append(("画面缺少明月", "在窗外明确呈现一轮明月"))
    if detected.get("moonlight_on_ground") is not True:
        failures.append(("床前地面月光不明确", "强化床前地面的冷白月光光斑"))
    if detected.get("ancient_bed") is not True:
        failures.append(("画面缺少明确的古代床榻", "加入结构清晰的古代木质床榻"))
    if detected.get("modern_objects") is True:
        failures.append(("画面出现现代元素", "移除所有现代物品和现代家具"))
    if detected.get("snow_or_real_frost") is True:
        failures.append(("画面出现雪花或真实冰霜", "只表现如霜月光，不出现真实冰霜或雪花"))
    if detected.get("artificial_light") is True:
        failures.append(("画面出现灯具或人工照明", "移除灯笼、油灯、蜡烛和暖色人工光"))
    for issue, suggestion in failures:
        if issue not in issues:
            issues.append(issue)
        if suggestion not in advice:
            advice.append(suggestion)
    normalized["possible_errors"] = issues
    normalized["revision_advice"] = advice
    normalized["pass"] = not failures
    return normalized


def unavailable_vision_review(message: str) -> dict[str, Any]:
    return {
        "image_summary": message,
        "person_count": 0,
        "key_elements_detected": {
            "one_poet": False,
            "moon": False,
            "moonlight_on_ground": False,
            "ancient_bed": False,
            "modern_objects": False,
            "snow_or_real_frost": False,
            "artificial_light": False,
        },
        "missing_elements": ["图片的有效审核结果"],
        "possible_errors": ["图片审核结果不可用"],
        "pass": False,
        "revision_advice": [],
    }


VISION_TEXT_FIELDS = {
    "single_poet": "单一古代诗人",
    "moon": "明月",
    "moonlight_on_ground": "床前地面月光",
    "ancient_bed": "古代床榻",
    "modern_objects": "现代物品",
    "snow_or_real_frost": "真实冰霜或雪",
    "artificial_light": "人工照明",
}


def _vision_text_value(text: str, label: str) -> str | None:
    match = re.search(
        rf"(?:^|[；;])\s*{re.escape(label)}\s*[=＝:：]\s*([^；;]+)",
        text,
    )
    return match.group(1).strip() if match else None


def vision_review_from_text(text: str) -> dict[str, Any]:
    observation = " ".join(str(text).split()).strip()
    count_value = _vision_text_value(observation, "人物数量")
    values = {
        key: _vision_text_value(observation, label)
        for key, label in VISION_TEXT_FIELDS.items()
    }
    summary = _vision_text_value(observation, "画面概述") or observation
    reported_issues = _vision_text_value(observation, "问题")
    reported_advice = _vision_text_value(observation, "修改建议")
    if count_value is None or any(value is None for value in values.values()):
        review = unavailable_vision_review(
            "Qwen-VL 返回了看图文字，但固定观察字段不完整"
        )
        review["observation_text"] = observation
        review["possible_errors"].append("视觉观察报告字段不完整")
        return review

    count_match = re.search(r"\d+", count_value)
    person_count = int(count_match.group()) if count_match else 0
    invalid_values = []
    if values["single_poet"] not in {"是", "否"}:
        invalid_values.append("单一古代诗人")
    for key, label in VISION_TEXT_FIELDS.items():
        if key == "single_poet":
            continue
        if values[key] not in {"有", "无"}:
            invalid_values.append(label)
    if invalid_values:
        review = unavailable_vision_review(
            "Qwen-VL 返回了看图文字，但判断字段没有选择唯一值"
        )
        review["observation_text"] = observation
        review["possible_errors"].append(
            "视觉判断值无效：" + "、".join(invalid_values)
        )
        return review

    def positive(value: str | None) -> bool:
        return str(value).strip() in {"有", "是"}

    detected = {
        "one_poet": person_count == 1 and positive(values["single_poet"]),
        "moon": positive(values["moon"]),
        "moonlight_on_ground": positive(values["moonlight_on_ground"]),
        "ancient_bed": positive(values["ancient_bed"]),
        "modern_objects": positive(values["modern_objects"]),
        "snow_or_real_frost": positive(values["snow_or_real_frost"]),
        "artificial_light": positive(values["artificial_light"]),
    }
    normalized = normalize_vision_review(
        {
            "image_summary": summary,
            "person_count": person_count,
            "key_elements_detected": detected,
            "missing_elements": [],
            "possible_errors": [],
            "pass": False,
            "revision_advice": [],
        }
    )
    normalized["observation_text"] = observation
    if reported_issues and reported_issues != "无":
        normalized["reported_issues"] = [
            item.strip()
            for item in re.split(r"[,，、]", reported_issues)
            if item.strip()
        ]
    if reported_advice and reported_advice != "无":
        normalized["reported_advice"] = [
            item.strip()
            for item in re.split(r"[,，、]", reported_advice)
            if item.strip()
        ]
    return normalized


def build_final_decision(
    *,
    text_review: Mapping[str, Any],
    vision_review: Mapping[str, Any],
) -> dict[str, Any]:
    text_pass = text_review.get("pass") is True
    vision_pass = vision_review.get("pass") is True
    return {
        "pass": text_pass and vision_pass,
        "text_pass": text_pass,
        "vision_pass": vision_pass,
        "fallback_used": bool(text_review.get("fallback_used")),
        "failed_parts": [
            part
            for part, passed in (
                ("text", text_pass),
                ("vision", vision_pass),
            )
            if not passed
        ],
    }


def normalize_text_review(review: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(review)
    issue_fields = ("knowledge_issues", "quiz_issues", "teaching_issues")
    for field in issue_fields:
        normalized[field] = list(normalized.get(field) or [])
    normalized["required_actions"] = list(
        normalized.get("required_actions") or []
    )
    has_issues = any(normalized[field] for field in issue_fields) or bool(
        normalized["required_actions"]
    )
    normalized["pass"] = not has_issues
    if has_issues:
        normalized["review_result"] = "needs_revision"
    elif normalized.get("fallback_used"):
        normalized["review_result"] = "fallback_review"
    else:
        normalized["review_result"] = "pass"
    return normalized


class GpuLearningWorkflow:
    _single_gpu_workflow_lock = threading.Lock()

    def __init__(
        self,
        *,
        db_path: str,
        output_root: str,
        qwen_client: QwenAwqClient | None = None,
        kolors_client: KolorsClient | None = None,
        vision_client: QwenVisionClient | None = None,
        deepseek_client: DeepSeekClient | None = None,
        prompt_compiler: KolorsPromptCompiler | None = None,
    ) -> None:
        self.db_path = db_path
        self.output_root = Path(output_root).resolve()
        self.qwen_client = qwen_client or QwenAwqClient()
        self.kolors_client = kolors_client or KolorsClient(
            output_root=self.output_root
        )
        self.vision_client = vision_client or QwenVisionClient(
            output_root=self.output_root
        )
        self.deepseek_client = deepseek_client or DeepSeekClient()
        self.prompt_compiler = prompt_compiler or KolorsPromptCompiler()

    def _run_text_review(
        self,
        *,
        review_input: Mapping[str, Any],
        emit: Callable[[WorkflowEvent], None],
    ) -> dict[str, Any]:
        emit(
            WorkflowEvent(
                "deepseek_review",
                "正在审核文字教学资源",
                "text_reviewer",
            )
        )
        review = None
        for attempt in range(2):
            try:
                review = self.deepseek_client.review(
                    review_input=review_input,
                    output_schema=TEXT_REVIEW_SCHEMA,
                )
                break
            except DeepSeekReviewError:
                if attempt == 0:
                    emit(
                        WorkflowEvent(
                            "deepseek_review",
                            "DeepSeek 短暂失败，正在进行一次短重试",
                            "text_reviewer",
                            status="running",
                        )
                    )
                    time.sleep(0.2)
        if review is None:
            emit(
                WorkflowEvent(
                    "local_review_d2",
                    "DeepSeek 暂不可用，正在使用本地 Qwen 审核文字资源",
                    "text_reviewer",
                )
            )
            fallback = self.qwen_client.run_text(
                QwenTextRequest(
                    task_name="local_text_review",
                    system_prompt=(
                        "你是古诗文文字教学资源审核员。只检查作者、朝代、释义、"
                        "意象、情感、讲解、课堂问题、测评题和 rubric；不要审核图片。"
                    ),
                    user_prompt=json.dumps(
                        review_input,
                        ensure_ascii=False,
                    ),
                    output_schema=TEXT_REVIEW_SCHEMA,
                    max_input_tokens=8192,
                    max_new_tokens=768,
                    temperature=0.0,
                )
            )
            review = dict(fallback.output)
            review["reviewer"] = "qwen2.5-14b-awq-local"
            review["fallback_used"] = True
        return normalize_text_review(review)

    @staticmethod
    def _text_review_input(
        *,
        poem: str,
        student_profile: Mapping[str, Any],
        text_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        resources = deepcopy(text_result["agent_outputs"])
        learning_resources = resources.get("learning_resources") or {}
        learning_resources.pop("standard_prompt_json", None)
        learning_resources.pop("quality_prompts", None)
        learning_resources.pop("image_prompt", None)
        resources.pop("local_review", None)
        return {
            "scope": "text_only",
            "poem": poem,
            "student_profile": dict(student_profile),
            "rag_context": text_result["rag_context"],
            "text_resources": resources,
            "review_requirements": [
                "核对作者、朝代、原文、释义和情感是否与 RAG 证据一致",
                "检查分层讲解、课堂导入和启发问题是否适合学生画像",
                "检查固定四题及 rubric 是否准确并对齐学习目标",
                "不要审核图片、构图或视觉元素",
            ],
        }

    def _rewrite_text_outputs_from_review(
        self,
        *,
        poem: str,
        student_profile: Mapping[str, Any],
        text_result: Mapping[str, Any],
        text_review: Mapping[str, Any],
    ) -> dict[str, Any]:
        outputs = text_result["agent_outputs"]
        resources = deepcopy(outputs.get("learning_resources") or {})
        for private_key in (
            "standard_prompt_json",
            "quality_prompts",
            "image_prompt",
        ):
            resources.pop(private_key, None)
        agent_input = {
            "poem": poem,
            "student_profile": dict(student_profile),
            "rag_context": deepcopy(text_result.get("rag_context") or []),
            "previous_output": {
                "poem_analysis": deepcopy(outputs.get("poem_analysis") or {}),
                "learning_resources": resources,
                "quiz": deepcopy(outputs.get("quiz") or {}),
            },
            "deepseek_review": {
                "knowledge_issues": list(
                    text_review.get("knowledge_issues") or []
                ),
                "quiz_issues": list(text_review.get("quiz_issues") or []),
                "teaching_issues": list(
                    text_review.get("teaching_issues") or []
                ),
                "required_actions": list(
                    text_review.get("required_actions") or []
                ),
                "review_summary": text_review.get("review_summary") or "",
            },
            "preserve_instruction": (
                "只修正文字教学资源、诗句解析和测评题；不得生成或修改"
                "standard_prompt_json、image_prompt、quality_prompts 或任何图片内容"
            ),
        }
        revised = self.qwen_client.run_text(
            QwenTextRequest(
                task_name="rewrite_text_resources_from_deepseek_feedback",
                system_prompt=(
                    "你是诗境智学的资源修正 Agent。DeepSeek 已给出明确审核意见。"
                    "必须逐项落实 required_actions，并修正对应的知识、教学和测评问题。"
                    "不得忽略、弱化或自行改写审核意见；不得修改任何图片或生图 Prompt。"
                    "只输出符合 JSON Schema 的修正版文字资源。"
                ),
                user_prompt=json.dumps(agent_input, ensure_ascii=False),
                output_schema=TEXT_RESOURCE_REVISION_SCHEMA,
                max_input_tokens=8192,
                max_new_tokens=2048,
                temperature=0.1,
            )
        )
        return {
            "agent_input": agent_input,
            "output": deepcopy(revised.output),
            "metrics": dict(getattr(revised, "metrics", {}) or {}),
        }

    def _rewrite_image_prompt(
        self,
        *,
        poem: str,
        original_prompt_json: Mapping[str, Any],
        vision_review: Mapping[str, Any],
        vision_observation: str,
    ) -> dict[str, Any]:
        rewritten = self.qwen_client.run_text(
            QwenTextRequest(
                task_name="rewrite_image_prompt_from_vision_feedback",
                system_prompt=(
                    "你是古诗意象图 Prompt 修正器。只根据 Qwen-VL 的实际看图"
                    "问题和修改建议重写图片 Prompt。保留正确内容，修复失败项；"
                    "输出一份全新的结构化画面 JSON，不要输出 Kolors 自然语言"
                    "Prompt。根据失败项实质修改 scene、subject、action、"
                    "composition、visual_focus、light、avoid 和约束。"
                ),
                user_prompt=json.dumps(
                    {
                        "poem": poem,
                        "original_standard_prompt_json": dict(
                            original_prompt_json
                        ),
                        "qwen_vl_observation_text": vision_observation,
                        "vision_review": dict(vision_review),
                    },
                    ensure_ascii=False,
                ),
                output_schema=STANDARD_PROMPT_SCHEMA,
                max_input_tokens=4096,
                max_new_tokens=768,
                temperature=0.1,
                seed=20260621,
            )
        )
        raw_output = dict(rewritten.output)
        applied_output = deepcopy(raw_output)
        detected = vision_review.get("key_elements_detected") or {}
        image_summary = str(vision_review.get("image_summary") or "")
        if detected.get("one_poet") is not True:
            applied_output["subject"] = "一名古代诗人"
            applied_output["action"] = (
                "侧身坐在古代木质床榻旁，低头望向床前月光"
            )
            applied_output["composition"] = (
                "人物与古代木质床榻占据前景和画面主体，约占画面三分之二，"
                "木格窗和窗外明月位于背景，避免只呈现窗景或纯风景"
            )
            constraints = list(
                applied_output.get("composition_constraints") or []
            )
            if "画面中只出现一名古代诗人" not in constraints:
                constraints.append("画面中只出现一名古代诗人")
            applied_output["composition_constraints"] = constraints
        if detected.get("moon") is not True:
            focus = list(applied_output.get("visual_focus") or [])
            if "窗外一轮清晰明月" not in focus:
                focus.append("窗外一轮清晰明月")
            applied_output["visual_focus"] = focus
        if detected.get("moonlight_on_ground") is not True:
            applied_output["light"] = (
                "冷白月光从窗外照入，在床前地面形成清晰明亮光斑"
            )
        if detected.get("ancient_bed") is not True:
            applied_output["composition"] = (
                "中景室内构图，诗人紧邻结构清晰的古代木质床榻，"
                "床榻、人物、明月和床前地面同时可见"
            )
            focus = list(applied_output.get("visual_focus") or [])
            if "结构清晰的古代木质床榻" not in focus:
                focus.append("结构清晰的古代木质床榻")
            applied_output["visual_focus"] = focus
        avoid = list(applied_output.get("avoid") or [])
        if detected.get("one_poet") is not True:
            avoid.extend(["无人", "空房间", "人物缺失", "纯风景", "只有窗景"])
        if detected.get("ancient_bed") is not True:
            avoid.extend(["现代床", "帐篷", "被布覆盖的不明物体"])
        if detected.get("modern_objects") is True:
            avoid.extend(["现代物品", "现代家具"])
            for visible_object in ("盆栽", "花瓶", "窗台"):
                if visible_object in image_summary:
                    avoid.append(visible_object)
        if detected.get("snow_or_real_frost") is True:
            avoid.extend(["真实冰霜", "雪花"])
        if detected.get("artificial_light") is True:
            avoid.extend(
                ["灯笼", "油灯", "蜡烛", "暖色人工光"]
            )
        applied_output["avoid"] = list(dict.fromkeys(avoid))
        return {
            "raw_output": raw_output,
            "output": applied_output,
            "metrics": dict(rewritten.metrics),
        }

    def _compile_kolors_prompt(
        self,
        *,
        job_id: str,
        round_name: str,
        standard_prompt_json: Mapping[str, Any],
    ) -> dict[str, str]:
        compiled = self.prompt_compiler.compile(
            standard_prompt_json
        ).as_dict()
        logger.info(
            "Kolors compiled prompt job=%s round=%s zh_prompt=%s "
            "negative_prompt=%s",
            job_id,
            round_name,
            compiled["zh_prompt"],
            compiled["negative_prompt"],
        )
        return compiled

    def _review_image(
        self,
        *,
        image_path: str,
    ):
        return self.vision_client.review(
            QwenVisionRequest(
                task_name="vision_review",
                image_path=image_path,
                prompt=(
                    "客观检查图片中的人物数量、古代床榻、明月、床前地面月光、"
                    "现代物品、雪花或真实冰霜和明显错误。不要根据文字提示猜测，"
                    "只报告实际看见的内容。人工灯具、灯笼、油灯和暖色室内光必须"
                    "作为问题报告。画面概述必须简短，问题和修改建议只写关键项。"
                ),
                response_mode="text",
                max_new_tokens=256,
            )
        )

    @staticmethod
    def _vision_result_to_review(vision: Any) -> tuple[dict[str, Any], str]:
        output = dict(getattr(vision, "output", {}) or {})
        observation = str(
            output.get("observation_text")
            or getattr(vision, "raw_text", "")
            or ""
        ).strip()
        if observation:
            return vision_review_from_text(observation), observation
        return normalize_vision_review(output), json.dumps(
            output,
            ensure_ascii=False,
        )

    def run(
        self,
        *,
        poem: str,
        student_profile: Mapping[str, Any],
        job_id: str | None = None,
        on_event: Callable[[WorkflowEvent], None] | None = None,
    ) -> dict[str, Any]:
        actual_job_id = job_id or f"job_{uuid4().hex[:16]}"
        emit = on_event or (lambda event: None)
        with self._single_gpu_workflow_lock:
            emit(
                WorkflowEvent(
                    "text_stage",
                    "Qwen 正在分析诗句与学生画像",
                    "poem_analysis",
                )
            )
            text_result = TextStageRunner(
                db_path=self.db_path,
                client=self.qwen_client,
            ).run(poem=poem, student_profile=student_profile)

            learning_resources = text_result["agent_outputs"][
                "learning_resources"
            ]
            emit(
                WorkflowEvent(
                    "text_stage",
                    "诗句解析与学情诊断已完成",
                    "poem_analysis",
                    {
                        "student_diagnosis": text_result["agent_outputs"].get(
                            "student_diagnosis"
                        ),
                        "poem_analysis": text_result["agent_outputs"].get(
                            "poem_analysis"
                        ),
                    },
                )
            )
            emit(
                WorkflowEvent(
                    "text_stage",
                    "正在整理角色化教学资源与固定四题",
                    "text_resources",
                    status="running",
                )
            )
            emit(
                WorkflowEvent(
                    "text_stage",
                    "角色化教学资源与固定四题已生成",
                    "text_resources",
                    {
                        "audience_role": student_profile.get("audience_role"),
                        "learning_resources": learning_resources,
                        "quiz": text_result["agent_outputs"].get("quiz"),
                    },
                )
            )
            standard_prompt_json = deepcopy(
                learning_resources["standard_prompt_json"]
            )
            emit(
                WorkflowEvent(
                    "text_stage",
                    "正在提取标准化画面 JSON",
                    "image_prompt",
                    status="running",
                )
            )
            emit(
                WorkflowEvent(
                    "text_stage",
                    "标准化画面 JSON 已生成",
                    "image_prompt",
                    standard_prompt_json,
                )
            )
            emit(
                WorkflowEvent(
                    "text_stage",
                    "正在把标准画面 JSON 编译为 Kolors Prompt",
                    "prompt_compiler",
                    status="running",
                )
            )
            compiled_prompt = self._compile_kolors_prompt(
                job_id=actual_job_id,
                round_name="initial",
                standard_prompt_json=standard_prompt_json,
            )
            learning_resources["quality_prompts"] = {
                "kolors": deepcopy(compiled_prompt)
            }
            learning_resources["image_prompt"] = deepcopy(compiled_prompt)
            emit(
                WorkflowEvent(
                    "text_stage",
                    "Kolors 中文 Prompt 编译完成",
                    "prompt_compiler",
                    compiled_prompt,
                )
            )
            emit(
                WorkflowEvent(
                    "image_generation",
                    "标准画面 JSON 已编译，Kolors 正在生成古诗意境图",
                    "kolors",
                )
            )
            image = self.kolors_client.generate(
                KolorsRequest(
                    prompt=compiled_prompt["zh_prompt"],
                    negative_prompt=compiled_prompt["negative_prompt"],
                    output_dir=f"{actual_job_id}/images",
                    seed=20260620,
                    width=768,
                    height=768,
                    steps=20,
                    guidance_scale=6.0,
                )
            )
            emit(
                WorkflowEvent(
                    "image_generation",
                    "Kolors 初始图片已生成",
                    "kolors",
                    asdict(image),
                )
            )

            emit(
                WorkflowEvent(
                    "vision_review",
                    "Qwen-VL 正在识别人物、明月、床榻和错误元素",
                    "vision_reviewer",
                )
            )
            vision = self._review_image(image_path=image.image_path)
            vision_review, vision_observation = self._vision_result_to_review(
                vision
            )
            emit(
                WorkflowEvent(
                    "vision_review",
                    "Qwen-VL 初轮图片审核完成",
                    "vision_reviewer",
                    vision_review,
                )
            )
            correction_history = []
            active_standard_prompt_json = deepcopy(standard_prompt_json)
            active_compiled_prompt = deepcopy(compiled_prompt)
            if not vision_review["pass"]:
                emit(
                    WorkflowEvent(
                        "image_correction",
                        "图像审核未通过，正在由 Qwen 重写 Prompt 并重绘一次",
                        "image_prompt",
                    )
                )
                prompt_revision = self._rewrite_image_prompt(
                    poem=poem,
                    original_prompt_json=standard_prompt_json,
                    vision_review=vision_review,
                    vision_observation=vision_observation,
                )
                revised_standard_prompt_json = prompt_revision["output"]
                emit(
                    WorkflowEvent(
                        "image_correction",
                        "修正版标准画面 JSON 已完成",
                        "image_prompt",
                        revised_standard_prompt_json,
                    )
                )
                emit(
                    WorkflowEvent(
                        "image_correction",
                        "正在编译修正版 Kolors Prompt",
                        "prompt_compiler",
                        status="running",
                    )
                )
                revised_compiled_prompt = self._compile_kolors_prompt(
                    job_id=actual_job_id,
                    round_name="revision_1",
                    standard_prompt_json=revised_standard_prompt_json,
                )
                emit(
                    WorkflowEvent(
                        "image_correction",
                        "修正版 Kolors Prompt 已完成",
                        "prompt_compiler",
                        {
                            "standard_prompt_json": revised_standard_prompt_json,
                            "kolors_prompt": revised_compiled_prompt,
                        },
                    )
                )
                emit(
                    WorkflowEvent(
                        "image_correction",
                        "Kolors 正在执行单轮重绘",
                        "kolors",
                        status="running",
                    )
                )
                revised_image = self.kolors_client.generate(
                    KolorsRequest(
                        prompt=revised_compiled_prompt["zh_prompt"],
                        negative_prompt=revised_compiled_prompt[
                            "negative_prompt"
                        ],
                        output_dir=f"{actual_job_id}/images/revision_1",
                        seed=20260621,
                        width=768,
                        height=768,
                        steps=24,
                        guidance_scale=6.0,
                    )
                )
                emit(
                    WorkflowEvent(
                        "image_correction",
                        "Kolors 单轮重绘已完成",
                        "kolors",
                        asdict(revised_image),
                    )
                )
                emit(
                    WorkflowEvent(
                        "vision_review",
                        "Qwen-VL 正在审核单轮重绘图片",
                        "vision_reviewer",
                    )
                )
                revised_vision = None
                try:
                    revised_vision = self._review_image(
                        image_path=revised_image.image_path
                    )
                    (
                        revised_vision_review,
                        revised_vision_observation,
                    ) = self._vision_result_to_review(
                        revised_vision
                    )
                except RuntimeError as exc:
                    raw_error = str(exc)
                    if (
                        "视觉模型连续三次未返回合法 JSON" not in raw_error
                        and "模型输出无法解析为 JSON 对象" not in raw_error
                    ):
                        raise
                    logger.warning(
                        "Revised image review unavailable job=%s: %s",
                        actual_job_id,
                        raw_error,
                    )
                    revised_vision_review = unavailable_vision_review(
                        "重绘图片已生成，但 Qwen-VL 未返回合法结构化审核结果"
                    )
                    revised_vision_observation = ""
                emit(
                    WorkflowEvent(
                        "vision_review",
                        "Qwen-VL 重绘图片审核完成",
                        "vision_reviewer",
                        revised_vision_review,
                    )
                )
                correction_history.append(
                    {
                        "round": 1,
                        "before_image": asdict(image),
                        "before_vision_review": vision_review,
                        "before_vision_observation": vision_observation,
                        "vision_feedback": {
                            "issues": vision_review["possible_errors"],
                            "revision_advice": vision_review["revision_advice"],
                        },
                        "before_standard_prompt_json": standard_prompt_json,
                        "before_kolors_prompt": compiled_prompt,
                        "qwen_standard_prompt_revision": prompt_revision,
                        "after_standard_prompt_json": (
                            revised_standard_prompt_json
                        ),
                        "after_kolors_prompt": revised_compiled_prompt,
                        "after_image": asdict(revised_image),
                        "after_vision_review": revised_vision_review,
                        "after_vision_observation": (
                            revised_vision_observation
                        ),
                    }
                )
                image = revised_image
                if revised_vision is not None:
                    vision = revised_vision
                vision_review = revised_vision_review
                active_standard_prompt_json = deepcopy(
                    revised_standard_prompt_json
                )
                active_compiled_prompt = deepcopy(revised_compiled_prompt)
                learning_resources["quality_prompts"]["kolors"] = deepcopy(
                    revised_compiled_prompt
                )
                learning_resources["image_prompt"] = deepcopy(
                    revised_compiled_prompt
                )

            text_review = self._run_text_review(
                review_input=self._text_review_input(
                    poem=poem,
                    student_profile=student_profile,
                    text_result=text_result,
                ),
                emit=emit,
            )
            emit(
                WorkflowEvent(
                    (
                        "local_review_d2"
                        if text_review.get("fallback_used")
                        else "deepseek_review"
                    ),
                    "文字教学资源审核完成",
                    "text_reviewer",
                    text_review,
                )
            )
            text_correction_history = []
            if text_review.get("pass") is not True:
                emit(
                    WorkflowEvent(
                        "text_stage",
                        "文字审核未通过，资源生成 Agent 正在按审核意见修正一次",
                        "text_resources",
                        status="running",
                    )
                )
                before_outputs = {
                    "poem_analysis": deepcopy(
                        text_result["agent_outputs"].get("poem_analysis")
                    ),
                    "learning_resources": {
                        key: deepcopy(value)
                        for key, value in learning_resources.items()
                        if key
                        not in {
                            "standard_prompt_json",
                            "quality_prompts",
                            "image_prompt",
                        }
                    },
                    "quiz": deepcopy(
                        text_result["agent_outputs"].get("quiz")
                    ),
                }
                text_revision = self._rewrite_text_outputs_from_review(
                    poem=poem,
                    student_profile=student_profile,
                    text_result=text_result,
                    text_review=text_review,
                )
                revised = text_revision["output"]
                text_result["agent_outputs"]["poem_analysis"] = deepcopy(
                    revised["poem_analysis"]
                )
                for key, value in revised["learning_resources"].items():
                    learning_resources[key] = deepcopy(value)
                text_result["agent_outputs"]["quiz"] = deepcopy(
                    revised["quiz"]
                )
                emit(
                    WorkflowEvent(
                        "text_stage",
                        "资源生成 Agent 已完成单轮文字修正",
                        "text_resources",
                        {
                            "learning_resources": revised[
                                "learning_resources"
                            ],
                            "quiz": revised["quiz"],
                        },
                    )
                )
                revised_review = self._run_text_review(
                    review_input=self._text_review_input(
                        poem=poem,
                        student_profile=student_profile,
                        text_result=text_result,
                    ),
                    emit=emit,
                )
                emit(
                    WorkflowEvent(
                        (
                            "local_review_d2"
                            if revised_review.get("fallback_used")
                            else "deepseek_review"
                        ),
                        "修正版文字教学资源复审完成",
                        "text_reviewer",
                        revised_review,
                    )
                )
                text_correction_history.append(
                    {
                        "round": 1,
                        "before_outputs": before_outputs,
                        "deepseek_feedback": {
                            key: deepcopy(text_review.get(key) or [])
                            for key in (
                                "knowledge_issues",
                                "quiz_issues",
                                "teaching_issues",
                                "required_actions",
                            )
                        },
                        "resource_agent_revision": text_revision,
                        "after_review": revised_review,
                    }
                )
                text_review = revised_review
            final_decision = build_final_decision(
                text_review=text_review,
                vision_review=vision_review,
            )
            image_payload = {
                **asdict(image),
                "prompt": active_compiled_prompt["zh_prompt"],
                "negative_prompt": active_compiled_prompt["negative_prompt"],
                "standard_prompt_json": active_standard_prompt_json,
                "kolors_prompt": active_compiled_prompt,
            }
            emit(
                WorkflowEvent(
                    (
                        "local_review_d2"
                        if text_review.get("fallback_used")
                        else "deepseek_review"
                    ),
                    "正在汇总文字与图像双门禁结果",
                    "final_gate",
                    status="running",
                )
            )

            result = {
                "job_id": actual_job_id,
                "poem": poem,
                "student_profile": dict(student_profile),
                "text_stage": text_result,
                "text_review": text_review,
                "image": image_payload,
                "prompt_snapshot": {
                    "initial_standard_prompt_json": standard_prompt_json,
                    "initial_kolors_prompt": compiled_prompt,
                    "final_standard_prompt_json": (
                        active_standard_prompt_json
                    ),
                    "final_kolors_prompt": active_compiled_prompt,
                },
                "vision_review": {
                    "output": vision_review,
                    "metrics": dict(vision.metrics),
                },
                "final_decision": final_decision,
                "final_review": {
                    **text_review,
                    "review_result": (
                        "pass" if final_decision["pass"] else "needs_revision"
                    ),
                    **final_decision,
                },
                "correction_history": correction_history,
                "text_correction_history": text_correction_history,
            }
            output_path = self.output_root / actual_job_id / "result.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["result_path"] = str(output_path)
            emit(
                WorkflowEvent(
                    "completed",
                    "双门禁判定完成，gpu 学习资源流水线已结束",
                    "final_gate",
                    final_decision,
                    "completed",
                )
            )
            return result
