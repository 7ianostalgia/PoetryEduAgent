from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.storage.db import normalize_text


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("tags_json", "payload_json", "row_json"):
        if key in data and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                pass
    return data


def _result_from_rows(
    poem: sqlite3.Row,
    knowledge: sqlite3.Row | None,
    match_type: str,
) -> dict[str, Any]:
    poem_dict = _row_to_dict(poem) or {}
    knowledge_dict = _row_to_dict(knowledge)
    source = knowledge if knowledge is not None else poem
    evidence = {
        "poem_id": poem["id"],
        "knowledge_id": knowledge["id"] if knowledge is not None else None,
        "source_db_hash": source["source_db_hash"],
        "source_table": source["source_table"],
        "source_pk": source["source_pk"],
    }
    return {
        "match_type": match_type,
        "poem": poem_dict,
        "knowledge": knowledge_dict,
        "evidence": evidence,
    }


def _knowledge_for_poem(
    conn: sqlite3.Connection,
    poem_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM poem_knowledge
        WHERE poem_id = ?
        ORDER BY
          CASE knowledge_type
            WHEN 'classroom_explanation' THEN 0
            WHEN 'translation' THEN 1
            WHEN 'theme' THEN 2
            ELSE 3
          END,
          id
        LIMIT 1
        """,
        (poem_id,),
    ).fetchone()


def search_poems(
    db_path: str | Path,
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search imported poem knowledge with exact-title, normalized-line, LIKE fallback."""

    text = query.strip()
    if not text:
        return []
    normalized = normalize_text(text)
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, int | None, str]] = set()

    def add_result(
        poem: sqlite3.Row,
        knowledge: sqlite3.Row | None,
        match_type: str,
    ) -> None:
        key = (
            int(poem["id"]),
            int(knowledge["id"]) if knowledge is not None else None,
            match_type,
        )
        if key in seen or len(results) >= limit:
            return
        seen.add(key)
        results.append(_result_from_rows(poem, knowledge, match_type))

    with _connect(db_path) as conn:
        for poem in conn.execute(
            """
            SELECT * FROM poems
            WHERE title = ? OR normalized_title = ?
            ORDER BY CASE WHEN title = ? THEN 0 ELSE 1 END, id
            LIMIT ?
            """,
            (text, normalized, text, limit),
        ):
            add_result(poem, _knowledge_for_poem(conn, int(poem["id"])), "title_exact")

        if normalized and len(results) < limit:
            needle = f"%{normalized}%"
            for row in conn.execute(
                """
                SELECT p.*, k.id AS k_id
                FROM poems AS p
                LEFT JOIN poem_knowledge AS k ON k.poem_id = p.id
                WHERE p.normalized_content LIKE ?
                   OR k.normalized_content LIKE ?
                ORDER BY
                  CASE
                    WHEN p.normalized_content LIKE ? THEN 0
                    ELSE 1
                  END,
                  p.id,
                  k.id
                LIMIT ?
                """,
                (needle, needle, needle, limit * 2),
            ):
                poem = conn.execute(
                    "SELECT * FROM poems WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                knowledge = (
                    conn.execute(
                        "SELECT * FROM poem_knowledge WHERE id = ?",
                        (row["k_id"],),
                    ).fetchone()
                    if row["k_id"] is not None
                    else _knowledge_for_poem(conn, int(row["id"]))
                )
                add_result(poem, knowledge, "normalized_line")
                if len(results) >= limit:
                    break

        if len(results) < limit:
            like = f"%{_escape_like(text)}%"
            for row in conn.execute(
                """
                SELECT p.id AS poem_id, k.id AS knowledge_id
                FROM poems AS p
                LEFT JOIN poem_knowledge AS k ON k.poem_id = p.id
                WHERE p.title LIKE ? ESCAPE '\\'
                   OR p.author LIKE ? ESCAPE '\\'
                   OR p.content LIKE ? ESCAPE '\\'
                   OR k.content LIKE ? ESCAPE '\\'
                ORDER BY p.id, k.id
                LIMIT ?
                """,
                (like, like, like, like, limit * 2),
            ):
                poem = conn.execute(
                    "SELECT * FROM poems WHERE id = ?",
                    (row["poem_id"],),
                ).fetchone()
                knowledge = (
                    conn.execute(
                        "SELECT * FROM poem_knowledge WHERE id = ?",
                        (row["knowledge_id"],),
                    ).fetchone()
                    if row["knowledge_id"] is not None
                    else _knowledge_for_poem(conn, int(row["poem_id"]))
                )
                add_result(poem, knowledge, "like_fallback")
                if len(results) >= limit:
                    break

    return results


def resolve_evidence(
    db_path: str | Path,
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the stored migrated rows behind a retrieval evidence object."""

    source_hash = evidence.get("source_db_hash")
    source_table = evidence.get("source_table")
    source_pk = evidence.get("source_pk")
    if not source_hash or not source_table or source_pk is None:
        return None
    with _connect(db_path) as conn:
        legacy = conn.execute(
            """
            SELECT * FROM legacy_raw
            WHERE source_db_hash = ?
              AND source_table = ?
              AND source_pk = ?
            """,
            (source_hash, source_table, str(source_pk)),
        ).fetchone()
        knowledge = None
        if evidence.get("knowledge_id") is not None:
            knowledge = conn.execute(
                "SELECT * FROM poem_knowledge WHERE id = ?",
                (evidence["knowledge_id"],),
            ).fetchone()
        poem = conn.execute(
            "SELECT * FROM poems WHERE id = ?",
            (evidence.get("poem_id"),),
        ).fetchone()
    return {
        "poem": _row_to_dict(poem),
        "knowledge": _row_to_dict(knowledge),
        "legacy_raw": _row_to_dict(legacy),
    }
