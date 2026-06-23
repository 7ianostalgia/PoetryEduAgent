from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


SCHEMA_VERSION = "2026-06-22-runtime-v4"
RUNTIME_TABLES = {
    "generations",
    "generation_cases",
    "failure_cases",
    "feedback_cases",
}
KNOWLEDGE_FIELDS = {
    "excerpt": "excerpt",
    "vernacular": "translation",
    "theme": "theme",
    "imagery_json": "imagery",
    "classroom_explanation": "classroom_explanation",
    "realistic_prompt": "realistic_prompt",
    "ink_prompt": "ink_prompt",
    "tags": "tags",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: Any) -> str:
    """Normalize Chinese poem text for duplicate detection and retrieval."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower()
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith(("P", "S", "Z", "C")):
            continue
        kept.append(char)
    return "".join(kept)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly_uri(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"


def connect_readonly_sqlite(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def integrity_check(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row is not None else "missing"


def connect_target(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            source_db_hash TEXT NOT NULL,
            source_integrity TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            poems_seen INTEGER NOT NULL DEFAULT 0,
            classroom_seen INTEGER NOT NULL DEFAULT 0,
            poems_inserted INTEGER NOT NULL DEFAULT 0,
            poems_updated INTEGER NOT NULL DEFAULT 0,
            knowledge_inserted INTEGER NOT NULL DEFAULT 0,
            skipped_runtime_tables TEXT NOT NULL DEFAULT '[]',
            report_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS legacy_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_db_hash TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_pk TEXT NOT NULL,
            row_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (source_db_hash, source_table, source_pk)
        );

        CREATE TABLE IF NOT EXISTS poems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            dynasty TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            normalized_title TEXT NOT NULL DEFAULT '',
            normalized_author TEXT NOT NULL DEFAULT '',
            normalized_content TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            source_db_hash TEXT,
            source_table TEXT,
            source_pk TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_poems_title_author
            ON poems (normalized_title, normalized_author);
        CREATE INDEX IF NOT EXISTS idx_poems_content
            ON poems (normalized_content);

        CREATE TABLE IF NOT EXISTS poem_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poem_id INTEGER NOT NULL REFERENCES poems(id) ON DELETE CASCADE,
            knowledge_type TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            normalized_content TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            grade_band TEXT,
            source_note TEXT,
            source_db_hash TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_pk TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (
                source_db_hash,
                source_table,
                source_pk,
                knowledge_type
            )
        );

        CREATE INDEX IF NOT EXISTS idx_knowledge_poem_id
            ON poem_knowledge (poem_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_source
            ON poem_knowledge (source_db_hash, source_table, source_pk);
        CREATE INDEX IF NOT EXISTS idx_knowledge_normalized_content
            ON poem_knowledge (normalized_content);

        CREATE TABLE IF NOT EXISTS student_profiles (
            id TEXT PRIMARY KEY,
            grade TEXT NOT NULL,
            level TEXT NOT NULL,
            weakness_json TEXT NOT NULL DEFAULT '[]',
            goal TEXT NOT NULL DEFAULT '',
            preference_json TEXT NOT NULL DEFAULT '{}',
            pretest_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS learning_jobs (
            id TEXT PRIMARY KEY,
            poem_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            poem_text TEXT NOT NULL DEFAULT '',
            student_profile_id TEXT REFERENCES student_profiles(id),
            status TEXT NOT NULL,
            current_stage TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '',
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_learning_jobs_status
            ON learning_jobs (status, updated_at);

        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES learning_jobs(id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            agent_id TEXT,
            event_status TEXT NOT NULL,
            message TEXT NOT NULL,
            output_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_job_events_job_id_id
            ON job_events (job_id, id);

        CREATE TABLE IF NOT EXISTS agent_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES learning_jobs(id) ON DELETE CASCADE,
            agent_name TEXT NOT NULL,
            stage TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS generated_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL UNIQUE
                REFERENCES learning_jobs(id) ON DELETE CASCADE,
            resource_type TEXT NOT NULL DEFAULT 'learning_bundle',
            content_json TEXT NOT NULL,
            review_status TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS image_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES learning_jobs(id) ON DELETE CASCADE,
            image_path TEXT NOT NULL,
            image_url TEXT,
            prompt TEXT NOT NULL DEFAULT '',
            negative_prompt TEXT NOT NULL DEFAULT '',
            seed INTEGER,
            vision_review_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS review_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES learning_jobs(id) ON DELETE CASCADE,
            reviewer TEXT NOT NULL,
            review_type TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            pass INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quiz_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL UNIQUE
                REFERENCES learning_jobs(id) ON DELETE CASCADE,
            quiz_json TEXT NOT NULL DEFAULT '{}',
            answers_json TEXT NOT NULL DEFAULT '{}',
            score REAL,
            weak_points_json TEXT NOT NULL DEFAULT '[]',
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feedback_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES learning_jobs(id) ON DELETE CASCADE,
            target_module TEXT NOT NULL,
            feedback TEXT NOT NULL,
            previous_output_json TEXT NOT NULL,
            agent_input_json TEXT NOT NULL,
            updated_module_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS question_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name TEXT NOT NULL,
            question_type TEXT NOT NULL,
            target_skill TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            template_json TEXT NOT NULL,
            example_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        """
    )
    columns = _table_columns(conn, "learning_jobs")
    if "role" not in columns:
        conn.execute(
            "ALTER TABLE learning_jobs ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"
        )
    conn.execute(
        """
        UPDATE learning_jobs
        SET role = (
            SELECT json_extract(generated_resources.content_json, '$.role')
            FROM generated_resources
            WHERE generated_resources.job_id = learning_jobs.id
        )
        WHERE EXISTS (
            SELECT 1
            FROM generated_resources
            WHERE generated_resources.job_id = learning_jobs.id
              AND json_extract(generated_resources.content_json, '$.role')
                  IN ('teacher', 'student')
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_learning_jobs_role "
        "ON learning_jobs (role, created_at)"
    )
    legacy_mode_label = "\u771f\u5b9e"
    mode_message_replacements = (
        (
            f"{legacy_mode_label}学习资源流水线已完成",
            "gpu 学习资源流水线已完成",
        ),
        (f"{legacy_mode_label}任务执行失败", "gpu 任务执行失败"),
    )
    conn.executemany(
        "UPDATE learning_jobs SET message = ? WHERE message = ?",
        [
            (current, legacy)
            for legacy, current in mode_message_replacements
        ],
    )
    conn.executemany(
        "UPDATE job_events SET message = ? WHERE message = ?",
        [
            (
                "gpu 任务已创建，正在等待 GPU",
                f"{legacy_mode_label}任务已创建，正在等待 GPU",
            ),
            (
                "双门禁判定完成，gpu 学习资源流水线已结束",
                (
                    "双门禁判定完成，"
                    f"{legacy_mode_label}学习资源流水线已结束"
                ),
            ),
            (
                "gpu 学习资源流水线已完成",
                f"{legacy_mode_label}学习资源流水线已完成",
            ),
        ],
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (version, applied_at)
        VALUES (?, ?)
        """,
        (SCHEMA_VERSION, utc_now_iso()),
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _select_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f'SELECT rowid AS __rowid__, * FROM "{table}"').fetchall()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys() if key != "__rowid__"}


def _source_pk(row: sqlite3.Row) -> str:
    try:
        value = row["id"]
    except (IndexError, KeyError):
        value = None
    return str(value if value not in (None, "") else row["__rowid__"])


def _first(row: sqlite3.Row, names: Iterable[str]) -> str:
    keys = set(row.keys())
    for name in names:
        if name in keys and row[name] not in (None, ""):
            return str(row[name]).strip()
    return ""


def _loads_tags(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        text = str(value).strip()
        try:
            parsed = json.loads(text)
            raw_items = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            separators = [",", "，", ";", "；", "|", "、"]
            for sep in separators[1:]:
                text = text.replace(sep, separators[0])
            raw_items = [item for item in text.split(separators[0]) if item.strip()]
    tags: list[str] = []
    for item in raw_items:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _merge_tags(existing_json: str, incoming: list[str]) -> str:
    merged = _loads_tags(existing_json)
    for tag in incoming:
        if tag not in merged:
            merged.append(tag)
    return _json_dumps(merged)


@dataclass
class PoemRecord:
    title: str
    author: str = ""
    dynasty: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    source_db_hash: str | None = None
    source_table: str | None = None
    source_pk: str | None = None

    @property
    def normalized_title(self) -> str:
        return normalize_text(self.title)

    @property
    def normalized_author(self) -> str:
        return normalize_text(self.author)

    @property
    def normalized_content(self) -> str:
        return normalize_text(self.content)


@dataclass
class MigrationReport:
    source_path: str
    target_path: str
    source_db_hash: str
    source_integrity: str
    dry_run: bool
    poems_seen: int = 0
    classroom_seen: int = 0
    poems_inserted: int = 0
    poems_updated: int = 0
    knowledge_inserted: int = 0
    legacy_raw_inserted: int = 0
    skipped_runtime_tables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "target_path": self.target_path,
            "source_db_hash": self.source_db_hash,
            "source_integrity": self.source_integrity,
            "dry_run": self.dry_run,
            "poems_seen": self.poems_seen,
            "classroom_seen": self.classroom_seen,
            "poems_inserted": self.poems_inserted,
            "poems_updated": self.poems_updated,
            "knowledge_inserted": self.knowledge_inserted,
            "legacy_raw_inserted": self.legacy_raw_inserted,
            "skipped_runtime_tables": self.skipped_runtime_tables,
        }


def _find_poem(conn: sqlite3.Connection, record: PoemRecord) -> sqlite3.Row | None:
    if record.normalized_content:
        row = conn.execute(
            """
            SELECT * FROM poems
            WHERE normalized_content = ?
            LIMIT 1
            """,
            (record.normalized_content,),
        ).fetchone()
        if row is not None:
            return row
        # 同一作者可能写有同题组诗，正文不同就必须保留为不同记录。
        # 只有源记录没有正文时，才允许退回标题与作者组合匹配。
        return None
    if record.normalized_title:
        return conn.execute(
            """
            SELECT * FROM poems
            WHERE normalized_title = ?
              AND normalized_author = ?
            LIMIT 1
            """,
            (record.normalized_title, record.normalized_author),
        ).fetchone()
    return None


def _upsert_poem(
    conn: sqlite3.Connection,
    record: PoemRecord,
    report: MigrationReport,
) -> int:
    now = utc_now_iso()
    existing = _find_poem(conn, record)
    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO poems (
                title,
                author,
                dynasty,
                content,
                normalized_title,
                normalized_author,
                normalized_content,
                tags_json,
                source_db_hash,
                source_table,
                source_pk,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.title,
                record.author,
                record.dynasty,
                record.content,
                record.normalized_title,
                record.normalized_author,
                record.normalized_content,
                _json_dumps(record.tags),
                record.source_db_hash,
                record.source_table,
                record.source_pk,
                now,
                now,
            ),
        )
        report.poems_inserted += 1
        return int(cursor.lastrowid)

    updates: dict[str, Any] = {}
    for field_name in ("title", "author", "dynasty", "content"):
        current = str(existing[field_name] or "")
        incoming = getattr(record, field_name)
        if incoming and (not current or len(incoming) > len(current)):
            updates[field_name] = incoming
            if field_name in {"title", "author", "content"}:
                updates[f"normalized_{field_name}"] = normalize_text(incoming)

    merged_tags = _merge_tags(str(existing["tags_json"] or "[]"), record.tags)
    if merged_tags != str(existing["tags_json"] or "[]"):
        updates["tags_json"] = merged_tags

    if not existing["source_db_hash"] and record.source_db_hash:
        updates["source_db_hash"] = record.source_db_hash
        updates["source_table"] = record.source_table
        updates["source_pk"] = record.source_pk

    if updates:
        updates["updated_at"] = now
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE poems SET {assignments} WHERE id = ?",
            (*updates.values(), existing["id"]),
        )
        report.poems_updated += 1
    return int(existing["id"])


def _insert_legacy_raw(
    conn: sqlite3.Connection,
    source_db_hash: str,
    source_table: str,
    source_pk: str,
    row: sqlite3.Row,
) -> bool:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO legacy_raw (
            source_db_hash,
            source_table,
            source_pk,
            row_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            source_db_hash,
            source_table,
            source_pk,
            _json_dumps(_row_to_dict(row)),
            utc_now_iso(),
        ),
    )
    return cursor.rowcount > 0


def _insert_knowledge(
    conn: sqlite3.Connection,
    poem_id: int,
    knowledge_type: str,
    content: str,
    payload: dict[str, Any],
    grade_band: str,
    source_note: str,
    source_db_hash: str,
    source_table: str,
    source_pk: str,
) -> bool:
    if not content and not payload:
        return False
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO poem_knowledge (
            poem_id,
            knowledge_type,
            content,
            normalized_content,
            payload_json,
            grade_band,
            source_note,
            source_db_hash,
            source_table,
            source_pk,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            poem_id,
            knowledge_type,
            content,
            normalize_text(content),
            _json_dumps(payload),
            grade_band or None,
            source_note or None,
            source_db_hash,
            source_table,
            source_pk,
            utc_now_iso(),
        ),
    )
    return cursor.rowcount > 0


def _poem_record_from_poems_row(
    row: sqlite3.Row,
    source_db_hash: str,
) -> PoemRecord:
    return PoemRecord(
        title=_first(row, ("title",)),
        author=_first(row, ("author",)),
        dynasty=_first(row, ("dynasty",)),
        content=_first(row, ("content", "full_text", "excerpt")),
        tags=_loads_tags(_first(row, ("tags",))),
        source_db_hash=source_db_hash,
        source_table="poems",
        source_pk=_source_pk(row),
    )


def _poem_record_from_classroom_row(
    row: sqlite3.Row,
    source_db_hash: str,
) -> PoemRecord:
    title = _first(row, ("title", "normalized_title"))
    full_text = _first(row, ("full_text", "content", "excerpt", "normalized_full_text"))
    if not title:
        title = full_text[:16] or f"legacy-classroom-{_source_pk(row)}"
    return PoemRecord(
        title=title,
        author=_first(row, ("author", "normalized_author")),
        dynasty=_first(row, ("dynasty",)),
        content=full_text,
        tags=_loads_tags(_first(row, ("tags",))),
        source_db_hash=source_db_hash,
        source_table="classroom_poems",
        source_pk=_source_pk(row),
    )


def _import_poems_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    source_db_hash: str,
    report: MigrationReport,
) -> None:
    if "poems" not in _table_names(source):
        return
    for row in _select_rows(source, "poems"):
        report.poems_seen += 1
        source_pk = _source_pk(row)
        if _insert_legacy_raw(target, source_db_hash, "poems", source_pk, row):
            report.legacy_raw_inserted += 1
        poem_id = _upsert_poem(
            target,
            _poem_record_from_poems_row(row, source_db_hash),
            report,
        )
        tags = _loads_tags(_first(row, ("tags",)))
        if tags and _insert_knowledge(
            target,
            poem_id,
            "tags",
            "、".join(tags),
            {"tags": tags},
            "",
            "",
            source_db_hash,
            "poems",
            source_pk,
        ):
            report.knowledge_inserted += 1


def _import_classroom_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    source_db_hash: str,
    report: MigrationReport,
) -> None:
    if "classroom_poems" not in _table_names(source):
        return
    columns = _table_columns(source, "classroom_poems")
    for row in _select_rows(source, "classroom_poems"):
        report.classroom_seen += 1
        source_pk = _source_pk(row)
        if _insert_legacy_raw(
            target,
            source_db_hash,
            "classroom_poems",
            source_pk,
            row,
        ):
            report.legacy_raw_inserted += 1
        poem_id = _upsert_poem(
            target,
            _poem_record_from_classroom_row(row, source_db_hash),
            report,
        )
        grade_band = _first(row, ("grade_band",))
        source_note = _first(row, ("source_note",))
        for column_name, knowledge_type in KNOWLEDGE_FIELDS.items():
            if column_name not in columns:
                continue
            raw = row[column_name]
            if raw in (None, ""):
                continue
            content = str(raw).strip()
            payload: dict[str, Any] = {}
            if column_name in {"imagery_json", "tags"}:
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = _loads_tags(content) if column_name == "tags" else content
                payload = {column_name: parsed}
            if _insert_knowledge(
                target,
                poem_id,
                knowledge_type,
                content,
                payload,
                grade_band,
                source_note,
                source_db_hash,
                "classroom_poems",
                source_pk,
            ):
                report.knowledge_inserted += 1


def migrate_legacy_database(
    source_path: str | Path,
    target_path: str | Path = "data/poetry_edu.db",
    *,
    dry_run: bool = False,
) -> MigrationReport:
    source_db = Path(source_path)
    target_db = Path(target_path)
    source_hash = sha256_file(source_db)
    started_at = utc_now_iso()

    with connect_readonly_sqlite(source_db) as source:
        check = integrity_check(source)
        if check.lower() != "ok":
            raise sqlite3.DatabaseError(f"source integrity_check failed: {check}")

        tables = _table_names(source)
        report = MigrationReport(
            source_path=str(source_db),
            target_path=str(target_db),
            source_db_hash=source_hash,
            source_integrity=check,
            dry_run=dry_run,
            skipped_runtime_tables=sorted(tables & RUNTIME_TABLES),
        )

        if dry_run:
            report.poems_seen = len(_select_rows(source, "poems")) if "poems" in tables else 0
            report.classroom_seen = (
                len(_select_rows(source, "classroom_poems"))
                if "classroom_poems" in tables
                else 0
            )
            return report

        with connect_target(target_db) as target:
            initialize_schema(target)
            with target:
                _import_poems_table(source, target, source_hash, report)
                _import_classroom_table(source, target, source_hash, report)
                completed_at = utc_now_iso()
                target.execute(
                    """
                    INSERT INTO migration_runs (
                        source_path,
                        source_db_hash,
                        source_integrity,
                        dry_run,
                        started_at,
                        completed_at,
                        poems_seen,
                        classroom_seen,
                        poems_inserted,
                        poems_updated,
                        knowledge_inserted,
                        skipped_runtime_tables,
                        report_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(source_db),
                        source_hash,
                        check,
                        int(dry_run),
                        started_at,
                        completed_at,
                        report.poems_seen,
                        report.classroom_seen,
                        report.poems_inserted,
                        report.poems_updated,
                        report.knowledge_inserted,
                        _json_dumps(report.skipped_runtime_tables),
                        _json_dumps(report.to_dict()),
                    ),
                )
    return report
