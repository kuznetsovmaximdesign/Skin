"""Висящие уточнения.

Открытый вопрос ровно один: пока он висит, следующее сообщение считается
ответом на него. Нет ответа сутки — вопрос закрывается сам, а запись уходит
в инбокс.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta

from .db import Database, utc_now_iso
from .dates import to_utc

log = logging.getLogger(__name__)

LIFETIME = timedelta(days=1)


class Questions:
    def __init__(self, db: Database, tz: str = "Europe/Moscow") -> None:
        self.db = db
        self.tz = tz

    def ask(
        self, *, raw_id: int, field: str, question: str, options: list[str], now: datetime
    ) -> int:
        rows = self.db.execute(
            """
            INSERT INTO pending_questions
                (created_at, raw_id, field, question, options_json, expires_at)
            VALUES (?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (
                utc_now_iso(),
                raw_id,
                field,
                question,
                json.dumps(options, ensure_ascii=False),
                to_utc(now + LIFETIME, self.tz),
            ),
        )
        question_id = int(rows[0]["id"])
        log.info("вопрос %s по полю %s", question_id, field)
        return question_id

    def open(self) -> sqlite3.Row | None:
        rows = self.db.execute(
            "SELECT * FROM pending_questions WHERE state = 'open' ORDER BY id LIMIT 1"
        )
        return rows[0] if rows else None

    def get(self, question_id: int) -> sqlite3.Row | None:
        rows = self.db.execute("SELECT * FROM pending_questions WHERE id = ?", (question_id,))
        return rows[0] if rows else None

    def options(self, question_id: int) -> list[str]:
        row = self.get(question_id)
        if row is None or not row["options_json"]:
            return []
        return list(json.loads(row["options_json"]))

    def close(self, question_id: int, *, state: str = "answered", answer_raw_id: int | None = None) -> bool:
        """Повторное нажатие той же кнопки второй раз ничего не делает."""
        row = self.get(question_id)
        if row is None or row["state"] != "open":
            return False
        self.db.execute(
            "UPDATE pending_questions SET state = ?, closed_at = ?, answer_raw_id = ? WHERE id = ?",
            (state, utc_now_iso(), answer_raw_id, question_id),
        )
        return True

    def expire(self, now: datetime) -> list[int]:
        """Сутки без ответа — вопрос закрывается, запись остаётся в инбоксе."""
        rows = self.db.execute(
            "SELECT id FROM pending_questions WHERE state = 'open' AND expires_at <= ?",
            (to_utc(now, self.tz),),
        )
        expired = [int(row["id"]) for row in rows]
        for question_id in expired:
            self.close(question_id, state="expired")
        return expired
