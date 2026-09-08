"""SQLite state store for the faceless-shorts pipeline.

Every pipeline stage reads/writes a `videos` row through this module —
see SPEC.md's Data model and status flow.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "state.db"

STATUSES = (
    "planned",
    "scripted",
    "voiced",
    "visuals_ready",
    "assembled",
    "captioned",
    "metadata_ready",
    "awaiting_review",
    "approved",
    "rejected",
    "uploaded",
    "failed",
)

_COLUMNS = (
    "id",
    "template",
    "status",
    "topic",
    "script_text",
    "code_snippet",
    "language",
    "hook",
    "audio_path",
    "video_path",
    "final_path",
    "title",
    "description",
    "tags",
    "youtube_video_id",
    "error_message",
    "approach",
    "cta_angle",
    "created_at",
    "updated_at",
)


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id                TEXT PRIMARY KEY,
                template          TEXT NOT NULL,
                status            TEXT NOT NULL,
                topic             TEXT,
                script_text       TEXT,
                code_snippet      TEXT,
                language          TEXT,
                hook              TEXT,
                audio_path        TEXT,
                video_path        TEXT,
                final_path        TEXT,
                title             TEXT,
                description       TEXT,
                tags              TEXT,
                youtube_video_id  TEXT,
                error_message     TEXT,
                approach          TEXT,
                cta_angle         TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
            """
        )
        # Migrations for columns added after the initial schema.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
        if "code_snippet" not in existing_cols:
            conn.execute("ALTER TABLE videos ADD COLUMN code_snippet TEXT")
        if "language" not in existing_cols:
            conn.execute("ALTER TABLE videos ADD COLUMN language TEXT")
        if "approach" not in existing_cols:
            conn.execute("ALTER TABLE videos ADD COLUMN approach TEXT")
        if "cta_angle" not in existing_cols:
            conn.execute("ALTER TABLE videos ADD COLUMN cta_angle TEXT")

        # video_steps: both templates break a video into narrated beats so
        # the visual can change exactly when the narration describing that
        # change plays — each beat's audio is synthesized separately,
        # giving an exact duration to drive the visual, rather than
        # guessing timing from a single narration pass. Programming:
        # buggy code + wrong output -> the fix -> corrected code + right
        # output (code_snippet/output_text populated, keywords NULL).
        # Facts: three quick distinct facts (keywords populated per beat
        # for keyword-matched stock footage, code_snippet/output_text
        # NULL). Quiz (quiz_longform): each question is TWO steps — a
        # "question" card (options/correct_index populated) then a
        # "reveal" card (script_text is the explanation narration) —
        # card_type distinguishes them, other templates leave it NULL.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_steps (
                video_id      TEXT NOT NULL,
                step_index    INTEGER NOT NULL,
                script_text   TEXT NOT NULL,
                code_snippet  TEXT,
                output_text   TEXT,
                keywords      TEXT,
                audio_path    TEXT,
                duration      REAL,
                card_type     TEXT,
                options       TEXT,
                correct_index INTEGER,
                PRIMARY KEY (video_id, step_index)
            )
            """
        )
        existing_step_cols = {row["name"] for row in conn.execute("PRAGMA table_info(video_steps)")}
        if "keywords" not in existing_step_cols:
            conn.execute("ALTER TABLE video_steps ADD COLUMN keywords TEXT")
        if "card_type" not in existing_step_cols:
            conn.execute("ALTER TABLE video_steps ADD COLUMN card_type TEXT")
        if "options" not in existing_step_cols:
            conn.execute("ALTER TABLE video_steps ADD COLUMN options TEXT")
        if "correct_index" not in existing_step_cols:
            conn.execute("ALTER TABLE video_steps ADD COLUMN correct_index INTEGER")

        # channel_stats: latest real subscriber/view counts, written by the
        # (future) weekly stats job once Phase 8 is live — never fabricated.
        # channel_milestones: the last threshold actually announced on
        # camera per metric, so the same milestone never gets mentioned
        # twice.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_stats (
                metric      TEXT PRIMARY KEY,
                value       INTEGER NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_milestones (
                metric              TEXT PRIMARY KEY,
                last_announced      INTEGER NOT NULL,
                updated_at          TEXT NOT NULL
            )
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_video(template: str, topic: str | None = None, db_path: Path = DB_PATH) -> str:
    video_id = str(uuid.uuid4())
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, template, status, topic, created_at, updated_at)
            VALUES (?, ?, 'planned', ?, ?, ?)
            """,
            (video_id, template, topic, now, now),
        )
    return video_id


def get_video(video_id: str, db_path: Path = DB_PATH) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    return dict(row) if row else None


def update_video(video_id: str, db_path: Path = DB_PATH, **fields) -> None:
    if not fields:
        return
    unknown = set(fields) - set(_COLUMNS)
    if unknown:
        raise ValueError(f"unknown video field(s): {sorted(unknown)}")
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in fields)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE videos SET {set_clause} WHERE id = ?",
            (*fields.values(), video_id),
        )


def list_by_status(status: str, db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE status = ? ORDER BY created_at", (status,)
        ).fetchall()
    return [dict(row) for row in rows]


_STEP_COLUMNS = (
    "script_text", "code_snippet", "output_text", "keywords", "audio_path", "duration",
    "card_type", "options", "correct_index",
)


def create_video_steps(video_id: str, steps: list[dict], db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM video_steps WHERE video_id = ?", (video_id,))
        for i, step in enumerate(steps, start=1):
            conn.execute(
                """
                INSERT INTO video_steps
                    (video_id, step_index, script_text, code_snippet, output_text, keywords,
                     card_type, options, correct_index)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id, i, step["script_text"], step.get("code_snippet"),
                    step.get("output_text"), step.get("keywords"),
                    step.get("card_type"), step.get("options"), step.get("correct_index"),
                ),
            )


def get_video_steps(video_id: str, db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM video_steps WHERE video_id = ? ORDER BY step_index", (video_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def update_video_step(video_id: str, step_index: int, db_path: Path = DB_PATH, **fields) -> None:
    if not fields:
        return
    unknown = set(fields) - set(_STEP_COLUMNS)
    if unknown:
        raise ValueError(f"unknown video_step field(s): {sorted(unknown)}")
    set_clause = ", ".join(f"{col} = ?" for col in fields)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE video_steps SET {set_clause} WHERE video_id = ? AND step_index = ?",
            (*fields.values(), video_id, step_index),
        )


def recent_topics(template: str, limit: int = 15, db_path: Path = DB_PATH) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT topic FROM videos
            WHERE template = ? AND topic IS NOT NULL
            ORDER BY created_at DESC LIMIT ?
            """,
            (template, limit),
        ).fetchall()
    return [row["topic"] for row in rows]


def set_channel_stat(metric: str, value: int, db_path: Path = DB_PATH) -> None:
    """Records the latest real pulled stat (e.g. from the weekly stats job).
    Never called with a guessed/rounded value — see pipeline/milestones.py."""
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO channel_stats (metric, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(metric) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (metric, value, now),
        )


def get_channel_stat(metric: str, db_path: Path = DB_PATH) -> int | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM channel_stats WHERE metric = ?", (metric,)).fetchone()
    return row["value"] if row else None


def get_last_announced_milestone(metric: str, db_path: Path = DB_PATH) -> int | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT last_announced FROM channel_milestones WHERE metric = ?", (metric,)
        ).fetchone()
    return row["last_announced"] if row else None


def set_last_announced_milestone(metric: str, value: int, db_path: Path = DB_PATH) -> None:
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO channel_milestones (metric, last_announced, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(metric) DO UPDATE SET last_announced = excluded.last_announced, updated_at = excluded.updated_at
            """,
            (metric, value, now),
        )


if __name__ == "__main__":
    init_db()
    print(f"initialized {DB_PATH}")
