"""SQLite. Схема применяется как есть из docs/life_bot_schema.sql."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "life_bot_schema.sql"

KINDS = ("text", "voice", "photo", "forward")


def utc_now_iso() -> str:
    """Время в базе — UTC ISO 8601, без микросекунд."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    """Одна база, одно соединение, доступ под замком.

    Пользователь один, нагрузка низкая: соединение переиспользуется, а вызовы
    из обработчиков уводятся в поток через asyncio.to_thread.
    """

    def __init__(self, path: Path | str, schema_path: Path | str = SCHEMA_PATH) -> None:
        self.path = Path(path)
        self.schema_path = Path(schema_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- жизненный цикл -------------------------------------------------

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        self._conn = conn
        self._apply_schema()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("база не открыта: сначала connect()")
        return self._conn

    def _apply_schema(self) -> None:
        with self._lock:
            exists = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inbox_raw'"
            ).fetchone()
            if exists:
                return
            log.info("применяю схему из %s", self.schema_path)
            self.conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            self.conn.execute("PRAGMA foreign_keys = ON")

    # -- сырой вход -----------------------------------------------------

    def save_raw(
        self,
        *,
        kind: str,
        tg_message_id: int | None = None,
        text: str | None = None,
        transcript: str | None = None,
        file_path: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """Пишет входящее до любого разбора. Возвращает id строки."""
        if kind not in KINDS:
            raise ValueError(f"недопустимый kind: {kind}")
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO inbox_raw (created_at, tg_message_id, kind, text, transcript, file_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (created_at or utc_now_iso(), tg_message_id, kind, text, transcript, file_path),
            )
            return int(cur.lastrowid)

    def find_raw_by_tg_id(self, tg_message_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM inbox_raw WHERE tg_message_id = ? ORDER BY id DESC LIMIT 1",
                (tg_message_id,),
            ).fetchone()

    def get_raw(self, raw_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute("SELECT * FROM inbox_raw WHERE id = ?", (raw_id,)).fetchone()

    def set_transcript(self, raw_id: int, transcript: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE inbox_raw SET transcript = ? WHERE id = ?", (transcript, raw_id)
            )

    def set_file_path(self, raw_id: int, file_path: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE inbox_raw SET file_path = ? WHERE id = ?", (file_path, raw_id)
            )

    def set_error(self, raw_id: int, error: str) -> None:
        """Ошибка пишется в строку, но сообщение остаётся. Терять нечего нельзя."""
        with self._lock:
            self.conn.execute("UPDATE inbox_raw SET error = ? WHERE id = ?", (error[:2000], raw_id))

    def set_parsed(
        self, raw_id: int, *, parser: str, parse_json: str | None = None, confidence: float | None = None
    ) -> None:
        """Разбор удался: запись больше не висит в инбоксе."""
        with self._lock:
            self.conn.execute(
                "UPDATE inbox_raw SET parse_state = 'parsed', parser = ?, parse_json = ?, "
                "confidence = ? WHERE id = ?",
                (parser, parse_json, confidence, raw_id),
            )

    def count_raw(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM inbox_raw").fetchone()
            return int(row["n"])

    # -- профиль и настройки --------------------------------------------

    def get_setting(self, key: str, profile_id: int = 1) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE profile_id = ? AND key = ?", (profile_id, key)
            ).fetchone()
            return None if row is None else str(row["value"])

    def all_settings(self, profile_id: int = 1) -> dict[str, str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT key, value FROM settings WHERE profile_id = ?", (profile_id,)
            ).fetchall()
            return {str(r["key"]): str(r["value"]) for r in rows}

    def get_profile(self, profile_id: int = 1) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()

    def bind_tg_user(self, tg_user_id: int, profile_id: int = 1) -> None:
        """Проставляет tg_user_id профилю один раз, молча."""
        with self._lock:
            self.conn.execute(
                "UPDATE profiles SET tg_user_id = ? WHERE id = ? AND tg_user_id IS NULL",
                (tg_user_id, profile_id),
            )

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())
