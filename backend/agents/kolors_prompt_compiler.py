from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


STANDARD_PROMPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "poem",
        "explanation",
        "scene",
        "subject",
        "action",
        "composition",
        "visual_focus",
        "light",
        "emotion",
        "style",
        "avoid",
        "composition_constraints",
    ],
    "additionalProperties": False,
    "properties": {
        "poem": {"type": "string"},
        "explanation": {"type": "string"},
        "scene": {"type": "string"},
        "subject": {"type": "string"},
        "action": {"type": "string"},
        "composition": {"type": "string"},
        "visual_focus": {"type": "array", "items": {"type": "string"}},
        "light": {"type": "string"},
        "emotion": {"type": "string"},
        "style": {"type": "string"},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "composition_constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


KOLORS_COMPILED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["zh_prompt", "negative_prompt"],
    "additionalProperties": False,
    "properties": {
        "zh_prompt": {"type": "string"},
        "negative_prompt": {"type": "string"},
    },
}


class KolorsPromptCompileError(ValueError):
    """Raised when a compiled prompt is not safe to send to Kolors."""


@dataclass(frozen=True)
class KolorsCompiledPrompt:
    zh_prompt: str
    negative_prompt: str

    def as_dict(self) -> dict[str, str]:
        return {
            "zh_prompt": self.zh_prompt,
            "negative_prompt": self.negative_prompt,
        }


class KolorsPromptCompiler:
    MIN_ZH_LENGTH = 120
    MAX_ZH_LENGTH = 220
    FORBIDDEN_LABELS = (
        "subject:",
        "composition:",
        "scene:",
        "style:",
        "主体：",
        "场景：",
        "构图：",
        "风格：",
    )
    COMMON_NEGATIVE = (
        "现代元素",
        "电器",
        "现代家具",
        "文字",
        "水印",
        "低质量",
        "畸形手",
        "错误肢体",
        "多余人物",
    )

    @staticmethod
    def _clean_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip(" ，。；：")

    @classmethod
    def _negative_tokens(cls, values: list[Any]) -> list[str]:
        tokens: list[str] = []
        for value in values:
            for item in re.split(r"[,，、;；。]+", cls._clean_text(value)):
                cleaned = re.sub(
                    r"^(禁止出现|禁止|不得出现|不要出现|避免|不要)",
                    "",
                    item,
                ).strip(" ：:")
                if cleaned and cleaned not in tokens:
                    tokens.append(cleaned)
        return tokens

    def compile(
        self,
        standard_prompt_json: Mapping[str, Any],
    ) -> KolorsCompiledPrompt:
        source = dict(standard_prompt_json)
        scene = self._clean_text(source.get("scene"))
        subject = self._clean_text(source.get("subject"))
        action = self._clean_text(source.get("action"))
        composition = self._clean_text(source.get("composition"))
        visual_focus = [
            self._clean_text(item)
            for item in source.get("visual_focus") or []
            if self._clean_text(item)
        ]
        light = self._clean_text(source.get("light"))
        emotion = self._clean_text(source.get("emotion"))
        style = self._clean_text(source.get("style"))
        constraints = [
            self._clean_text(item)
            for item in source.get("composition_constraints") or []
            if self._clean_text(item)
        ]

        sentences = [
            f"{scene}，{subject}{action}。",
            f"{composition}，画面重点清晰呈现{'、'.join(visual_focus)}。",
            f"{light}。",
        ]
        combined = " ".join(
            [
                self._clean_text(source.get("poem")),
                self._clean_text(source.get("explanation")),
                *visual_focus,
                *constraints,
            ]
        )
        if "霜" in combined:
            sentences.append("月色像霜一样铺开，但不是雪也不是真实冰霜。")
        if any(
            marker in combined
            for marker in ("一位", "一名", "只有一个", "只有一位", "单人")
        ):
            sentences.append("画面中只有一位人物，人物身份、姿态与环境关系明确。")
        sentences.append(
            f"整体氛围{emotion}，{style}，层次清楚，细节准确，画面完整，高质量。"
        )
        zh_prompt = "".join(item for item in sentences if item.strip())
        zh_prompt = re.sub(r"[，。；]{2,}", lambda m: m.group(0)[-1], zh_prompt)
        if len(zh_prompt) < self.MIN_ZH_LENGTH:
            zh_prompt += (
                "主体与环境比例自然，空间关系明确，光影过渡细腻，"
                "构图稳定，古代器物形制可信，中国画意境鲜明。"
            )
        if len(zh_prompt) > self.MAX_ZH_LENGTH:
            compact_sentences = [
                f"{scene}，{subject}{action}。",
                f"{composition}。",
                f"{light}。",
            ]
            if "霜" in combined:
                compact_sentences.append(
                    "月色像霜一样铺开，但不是雪也不是真实冰霜。"
                )
            if any(
                marker in combined
                for marker in ("一位", "一名", "只有一个", "只有一位", "单人")
            ):
                compact_sentences.append("画面中只有一位人物。")
            compact_sentences.append(
                f"氛围{emotion}，{style}，细节准确，高质量。"
            )
            zh_prompt = "".join(compact_sentences)
        if len(zh_prompt) > self.MAX_ZH_LENGTH:
            suffix = f"氛围{emotion}，{style}，细节准确，高质量。"
            compact_body = [
                f"{scene}，{subject}{action}。",
                f"{light}。",
                (
                    "月色像霜一样铺开，但不是雪也不是真实冰霜。"
                    if "霜" in combined
                    else ""
                ),
                (
                    "画面中只有一位人物。"
                    if any(
                        marker in combined
                        for marker in (
                            "一位",
                            "一名",
                            "只有一个",
                            "只有一位",
                            "单人",
                        )
                    )
                    else ""
                ),
            ]
            zh_prompt = "".join(compact_body) + suffix
        if len(zh_prompt) > self.MAX_ZH_LENGTH:
            allowed = self.MAX_ZH_LENGTH - len(suffix)
            body = zh_prompt[:allowed]
            boundary = max(body.rfind("。"), body.rfind("；"))
            if boundary >= self.MIN_ZH_LENGTH - len(suffix):
                body = body[: boundary + 1]
            else:
                comma = body.rfind("，")
                body = body[:comma].rstrip("，；。") + "。"
            zh_prompt = body + suffix

        negatives = self._negative_tokens(
            [*(source.get("avoid") or []), *self.COMMON_NEGATIVE]
        )
        if "霜" in self._clean_text(source.get("poem")):
            negatives.extend(
                item
                for item in (
                    "真实冰霜",
                    "雪花",
                    "飘雪",
                    "白色漂浮颗粒",
                    "灯笼",
                    "油灯",
                    "烛台",
                    "蜡烛",
                    "暖黄色灯光",
                )
                if item not in negatives
            )
        negative_prompt = "，".join(negatives)
        self.validate(zh_prompt, negative_prompt)
        return KolorsCompiledPrompt(
            zh_prompt=zh_prompt,
            negative_prompt=negative_prompt,
        )

    def validate(self, zh_prompt: str, negative_prompt: str) -> None:
        if not isinstance(zh_prompt, str) or not isinstance(
            negative_prompt, str
        ):
            raise KolorsPromptCompileError("Kolors prompt 必须是字符串")
        stripped = zh_prompt.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            raise KolorsPromptCompileError("zh_prompt 不得是 JSON")
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            raise KolorsPromptCompileError("zh_prompt 不得是 JSON")
        lowered = stripped.lower()
        if any(label.lower() in lowered for label in self.FORBIDDEN_LABELS):
            raise KolorsPromptCompileError("zh_prompt 含结构化字段标签")
        if "```" in stripped or "\n#" in stripped:
            raise KolorsPromptCompileError("zh_prompt 不得包含 Markdown")
        if not self.MIN_ZH_LENGTH <= len(stripped) <= self.MAX_ZH_LENGTH:
            raise KolorsPromptCompileError("zh_prompt 长度必须为 120 到 220 字")
        if not negative_prompt.strip():
            raise KolorsPromptCompileError("negative_prompt 不能为空")


def build_kolors_zh_prompt(
    standard_prompt_json: Mapping[str, Any],
) -> dict[str, str]:
    return KolorsPromptCompiler().compile(
        standard_prompt_json
    ).as_dict()
