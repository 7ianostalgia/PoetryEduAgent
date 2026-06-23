from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.rag.retrieval import resolve_evidence, search_poems
from backend.storage.db import migrate_legacy_database


def _make_legacy_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE poems (
                id INTEGER PRIMARY KEY,
                title TEXT,
                author TEXT,
                dynasty TEXT,
                content TEXT,
                tags TEXT
            );
            CREATE TABLE classroom_poems (
                id INTEGER PRIMARY KEY,
                title TEXT,
                author TEXT,
                dynasty TEXT,
                excerpt TEXT,
                full_text TEXT,
                vernacular TEXT,
                theme TEXT,
                imagery_json TEXT,
                classroom_explanation TEXT,
                realistic_prompt TEXT,
                ink_prompt TEXT,
                grade_band TEXT,
                source_note TEXT,
                tags TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO poems
            VALUES (1, '静夜思', '李白', '唐',
                    '床前明月光，疑是地上霜。举头望明月，低头思故乡。',
                    '思乡')
            """
        )
        conn.execute(
            """
            INSERT INTO classroom_poems
            VALUES (
                10,
                '静夜思',
                '李白',
                '唐',
                '床前明月光',
                '床前明月光，疑是地上霜。举头望明月，低头思故乡。',
                '月光像霜，引发诗人的故乡之思。',
                '思乡',
                '["月光", "霜"]',
                '通过明月、低头等动作体会乡愁。',
                'quiet moonlit bedroom',
                '水墨月夜，清辉如霜',
                '小学',
                'fixture',
                '月亮,思乡'
            )
            """
        )


def _migrated_db(tmp_path: Path) -> Path:
    source = tmp_path / "legacy.db"
    target = tmp_path / "poetry_edu.db"
    _make_legacy_db(source)
    migrate_legacy_database(source, target)
    return target


def test_retrieval_title_exact_and_evidence_round_trip(tmp_path: Path):
    target = _migrated_db(tmp_path)

    results = search_poems(target, "静夜思")

    assert results
    assert results[0]["match_type"] == "title_exact"
    assert results[0]["poem"]["title"] == "静夜思"
    assert results[0]["evidence"]["source_table"] in {"poems", "classroom_poems"}

    resolved = resolve_evidence(target, results[0]["evidence"])
    assert resolved is not None
    assert resolved["poem"]["title"] == "静夜思"
    assert resolved["legacy_raw"]["source_table"] == results[0]["evidence"]["source_table"]


def test_retrieval_normalized_line_ignores_spaces_and_punctuation(tmp_path: Path):
    target = _migrated_db(tmp_path)

    results = search_poems(target, "床 前 明月 光")

    assert results
    assert results[0]["match_type"] in {"normalized_line", "title_exact"}
    assert results[0]["poem"]["title"] == "静夜思"


def test_retrieval_like_fallback_searches_knowledge_text(tmp_path: Path):
    target = _migrated_db(tmp_path)

    results = search_poems(target, "乡愁")

    assert results
    assert any(result["match_type"] == "like_fallback" for result in results)
    assert any(
        result["knowledge"]
        and "乡愁" in result["knowledge"]["content"]
        for result in results
    )
