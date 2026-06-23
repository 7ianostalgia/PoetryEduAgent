from __future__ import annotations

import pytest

from backend.agents import KolorsPromptCompiler, build_kolors_zh_prompt
from backend.agents.kolors_prompt_compiler import KolorsPromptCompileError


STANDARD = {
    "poem": "床前明月光，疑是地上霜",
    "explanation": "月光照在床前，洁白得像霜，表达思乡之情",
    "scene": "古代中国室内夜晚",
    "subject": "一名唐代诗人",
    "action": "侧身坐在简朴的古代木质床榻旁，低头沉思",
    "composition": "中景单人构图，人物、床榻、木格窗和明月同时可见",
    "visual_focus": [
        "古代木质床榻",
        "窗外明月",
        "床前冷白月光光斑",
    ],
    "light": "清冷月光从木格窗外照入，照亮床前地面",
    "emotion": "安静、孤独、思乡",
    "style": "水墨写意，古风，中国画意境，留白充足，冷色调",
    "avoid": ["真实冰霜", "雪花", "现代家具", "灯笼", "油灯"],
    "composition_constraints": [
        "画面中只有一位人物",
        "月色像霜但地面没有真实冰霜",
    ],
}


def test_compiler_builds_kolors_natural_chinese_prompt():
    result = build_kolors_zh_prompt(STANDARD)
    assert 120 <= len(result["zh_prompt"]) <= 220
    assert "古代中国室内夜晚" in result["zh_prompt"]
    assert "月色像霜一样铺开，但不是雪也不是真实冰霜" in result["zh_prompt"]
    assert "画面中只有一位人物" in result["zh_prompt"]
    assert "主体：" not in result["zh_prompt"]
    assert "subject:" not in result["zh_prompt"]
    assert not result["zh_prompt"].startswith("{")
    assert "现代家具" in result["negative_prompt"]
    assert "真实冰霜" in result["negative_prompt"]
    assert "禁止出现" not in result["negative_prompt"]


def test_compiler_rejects_json_or_field_labels():
    compiler = KolorsPromptCompiler()
    with pytest.raises(KolorsPromptCompileError, match="JSON"):
        compiler.validate(
            '{"scene":"月夜"}',
            "现代元素",
        )
    with pytest.raises(KolorsPromptCompileError, match="字段标签"):
        compiler.validate(
            "主体：诗人" + "古代室内月夜意境" * 20,
            "现代元素",
        )


def test_compiler_shortens_at_sentence_boundary():
    source = {
        **STANDARD,
        "composition": "中景单人室内构图，" + "古代木质床榻细节清晰，" * 20,
    }
    result = build_kolors_zh_prompt(source)
    assert len(result["zh_prompt"]) <= 220
    assert result["zh_prompt"].endswith("。")
    assert not result["zh_prompt"].endswith("古代诗。")
    assert "水墨写意" in result["zh_prompt"]
    assert "高质量" in result["zh_prompt"]
