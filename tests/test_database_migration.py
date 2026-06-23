from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

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
                tags TEXT,
                normalized_title TEXT,
                normalized_author TEXT,
                normalized_full_text TEXT
            );

            CREATE TABLE generations (
                id INTEGER PRIMARY KEY,
                poem_id INTEGER,
                image_path TEXT,
                prompt TEXT
            );
            CREATE TABLE generation_cases (id INTEGER PRIMARY KEY, output_path TEXT);
            CREATE TABLE failure_cases (id INTEGER PRIMARY KEY, log_path TEXT);
            CREATE TABLE feedback_cases (id INTEGER PRIMARY KEY, screenshot_path TEXT);
            """
        )
        conn.execute(
            """
            INSERT INTO poems (id, title, author, dynasty, content, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "静夜思",
                "李白",
                "唐",
                "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
                "思乡,月亮",
            ),
        )
        conn.execute(
            """
            INSERT INTO classroom_poems (
                id,
                title,
                author,
                dynasty,
                excerpt,
                full_text,
                vernacular,
                theme,
                imagery_json,
                classroom_explanation,
                realistic_prompt,
                ink_prompt,
                grade_band,
                source_note,
                tags,
                normalized_title,
                normalized_author,
                normalized_full_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                10,
                "静夜思",
                "李白",
                "唐",
                "床前明月光",
                "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
                "明亮月光洒在床前，好像地上的霜。",
                "游子思乡",
                json.dumps(["明月", "霜"], ensure_ascii=False),
                "抓住月光、霜、举头、低头理解思乡情。",
                "moonlight in a quiet bedroom, homesick poet",
                "水墨月夜，床前清辉，诗人低头思乡",
                "小学",
                "fixture",
                json.dumps(["课堂", "思乡"], ensure_ascii=False),
                "静夜思",
                "李白",
                "床前明月光疑是地上霜举头望明月低头思故乡",
            ),
        )
        conn.execute(
            """
            INSERT INTO classroom_poems (
                id,
                title,
                author,
                dynasty,
                excerpt,
                full_text,
                vernacular,
                theme,
                imagery_json,
                classroom_explanation,
                realistic_prompt,
                ink_prompt,
                grade_band,
                source_note,
                tags
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                11,
                "春晓",
                "孟浩然",
                "唐",
                "春眠不觉晓",
                "春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。",
                "春夜睡得香甜，不知不觉天亮。",
                "惜春",
                json.dumps({"sound": "鸟鸣风雨"}, ensure_ascii=False),
                "从鸟鸣和风雨感受春天早晨。",
                "spring morning with birds and fallen petals",
                "水墨春晨，鸟鸣花落",
                "小学",
                "fixture",
                "春天",
            ),
        )
        conn.execute(
            """
            INSERT INTO generations (id, poem_id, image_path, prompt)
            VALUES (1, 1, '/tmp/private/generated.png', 'runtime prompt')
            """
        )


def test_migration_dry_run_validates_readonly_source_without_target_write(tmp_path: Path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "poetry_edu.db"
    _make_legacy_db(source)

    report = migrate_legacy_database(source, target, dry_run=True)

    assert report.dry_run is True
    assert report.source_integrity == "ok"
    assert report.source_db_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report.poems_seen == 1
    assert report.classroom_seen == 2
    assert report.skipped_runtime_tables == [
        "failure_cases",
        "feedback_cases",
        "generation_cases",
        "generations",
    ]
    assert not target.exists()


def test_migration_imports_knowledge_idempotently_and_skips_runtime_rows(
    tmp_path: Path,
):
    source = tmp_path / "legacy.db"
    target = tmp_path / "poetry_edu.db"
    _make_legacy_db(source)

    first = migrate_legacy_database(source, target)
    second = migrate_legacy_database(source, target)

    assert first.poems_inserted == 2
    assert first.classroom_seen == 2
    assert first.knowledge_inserted > 0
    assert second.poems_inserted == 0
    assert second.knowledge_inserted == 0

    with sqlite3.connect(target) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT COUNT(*) FROM poems").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM migration_runs").fetchone()[0] == 2
        assert (
            conn.execute(
                """
                SELECT COUNT(*)
                FROM poems
                WHERE title = '静夜思'
                  AND author = '李白'
                """
            ).fetchone()[0]
            == 1
        )
        legacy_tables = {
            row[0]
            for row in conn.execute("SELECT DISTINCT source_table FROM legacy_raw")
        }
        assert legacy_tables == {"poems", "classroom_poems"}
        runtime_paths = conn.execute(
            """
            SELECT COUNT(*)
            FROM legacy_raw
            WHERE row_json LIKE '%generated.png%'
               OR row_json LIKE '%runtime prompt%'
            """
        ).fetchone()[0]
        assert runtime_paths == 0
        knowledge = conn.execute(
            """
            SELECT *
            FROM poem_knowledge
            WHERE source_table = 'classroom_poems'
              AND source_pk = '10'
              AND knowledge_type = 'classroom_explanation'
            """
        ).fetchone()
        assert knowledge is not None
        assert knowledge["source_db_hash"] == first.source_db_hash
        assert knowledge["grade_band"] == "小学"
        assert knowledge["source_note"] == "fixture"


def test_same_title_and_author_with_different_content_are_preserved(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.db"
    target = tmp_path / "poetry_edu.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE poems (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT,
                dynasty TEXT,
                content TEXT NOT NULL,
                tags TEXT
            );
            INSERT INTO poems VALUES
                (1, '组诗', '诗人', '唐', '第一首正文。', '[]'),
                (2, '组诗', '诗人', '唐', '第二首正文。', '[]');
            """
        )

    migrate_legacy_database(source, target)

    with sqlite3.connect(target) as conn:
        rows = conn.execute(
            "SELECT content FROM poems ORDER BY id"
        ).fetchall()
    assert rows == [("第一首正文。",), ("第二首正文。",)]
