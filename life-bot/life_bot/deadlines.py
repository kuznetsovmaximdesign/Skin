"""Сроки: создание, выдача, закрытие, перенос, повторы.

Один факт — одна запись: строка в `records` плюс строка в `deadlines`.
Правки не переписывают запись молча, а ложатся в `record_edits`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from .db import Database, utc_now_iso
from .dates import When, to_local, to_utc

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Deadline:
    """Срок в локальном времени — таким его видит пользователь."""

    record_id: int
    title: str
    due_at: datetime
    remind_at: datetime
    category: str | None
    repeat_rule: str | None
    repeat_base: str
    sent_count: int
    snooze_count: int
    state: str

    def days_overdue(self, now: datetime) -> int:
        return max(0, (now.date() - self.due_at.date()).days)


def next_occurrence(
    due_at: datetime,
    rule: str | None,
    base: str,
    *,
    closed_at: datetime,
) -> datetime | None:
    """Следующий срок повторяющейся записи.

    `calendar` — жёсткая дата: отсчёт от исходного срока, поэтому закрытие с
    опозданием график не двигает. `done` — интервал от факта закрытия.
    """
    if not rule:
        return None

    if base == "done":
        interval = _interval(rule)
        if interval is not None:
            return closed_at + interval
        # Календарное правило с базой «от факта» — считаем от закрытия.
        return _advance(closed_at, rule)

    nxt = _advance(due_at, rule)
    if nxt is None:
        return None
    guard = 0
    while nxt <= closed_at and guard < 200:
        nxt = _advance(nxt, rule)
        guard += 1
    return nxt


def _interval(rule: str) -> timedelta | None:
    match = re.fullmatch(r"every:(\d+)([dm])", rule)
    if not match:
        return None
    number, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        return timedelta(days=number)
    return timedelta(days=30 * number)


def _advance(moment: datetime, rule: str) -> datetime | None:
    from dateutil.relativedelta import relativedelta

    if rule == "yearly":
        return moment + relativedelta(years=1)
    if rule == "monthly":
        return moment + relativedelta(months=1)
    if rule == "weekly":
        return moment + timedelta(days=7)
    if rule == "daily":
        return moment + timedelta(days=1)
    match = re.fullmatch(r"every:(\d+)([dm])", rule)
    if match:
        number, unit = int(match.group(1)), match.group(2)
        if unit == "m":
            return moment + relativedelta(months=number)
        return moment + timedelta(days=number)
    log.warning("неизвестное правило повтора: %s", rule)
    return None


class Deadlines:
    def __init__(self, db: Database, tz: str = "Europe/Moscow", profile_id: int = 1) -> None:
        self.db = db
        self.tz = tz
        self.profile_id = profile_id

    # -- создание -------------------------------------------------------

    def create(
        self,
        *,
        title: str,
        due_at: datetime,
        remind_at: datetime | None = None,
        raw_id: int | None = None,
        category: str | None = None,
        repeat_rule: str | None = None,
        repeat_base: str = "calendar",
    ) -> int:
        remind_at = remind_at or due_at
        with self.db._lock:  # noqa: SLF001 — одна транзакция на две таблицы
            cursor = self.db.conn.execute(
                "INSERT INTO records (created_at, profile_id, type, raw_id) VALUES (?, ?, 'deadline', ?)",
                (utc_now_iso(), self.profile_id, raw_id),
            )
            record_id = int(cursor.lastrowid)
            self.db.conn.execute(
                """
                INSERT INTO deadlines
                    (record_id, title, category, due_at, remind_at, repeat_rule, repeat_base)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    title,
                    category,
                    to_utc(due_at, self.tz),
                    to_utc(remind_at, self.tz),
                    repeat_rule,
                    repeat_base,
                ),
            )
        log.info("срок %s: %s на %s", record_id, title, due_at)
        return record_id

    def create_from_when(self, when: When, *, title: str | None = None, raw_id: int | None = None) -> int:
        return self.create(
            title=title or when.title or "без названия",
            due_at=when.due_at,
            remind_at=when.remind_at,
            raw_id=raw_id,
            repeat_rule=when.repeat_rule,
            repeat_base=when.repeat_base,
        )

    # -- выдача ---------------------------------------------------------

    def _row_to_deadline(self, row: sqlite3.Row) -> Deadline:
        return Deadline(
            record_id=int(row["record_id"]),
            title=str(row["title"]),
            due_at=to_local(str(row["due_at"]), self.tz),
            remind_at=to_local(str(row["remind_at"]), self.tz),
            category=row["category"],
            repeat_rule=row["repeat_rule"],
            repeat_base=str(row["repeat_base"]),
            sent_count=int(row["sent_count"]),
            snooze_count=int(row["snooze_count"]),
            state=str(row["state"]),
        )

    def get(self, record_id: int) -> Deadline | None:
        rows = self.db.execute(
            """
            SELECT d.*, r.state FROM deadlines d
            JOIN records r ON r.id = d.record_id
            WHERE d.record_id = ?
            """,
            (record_id,),
        )
        return self._row_to_deadline(rows[0]) if rows else None

    def _active(self, where: str, params: tuple) -> list[Deadline]:
        rows = self.db.execute(
            f"""
            SELECT d.*, r.state FROM deadlines d
            JOIN records r ON r.id = d.record_id
            WHERE r.state = 'active' AND r.profile_id = ? AND {where}
            ORDER BY d.due_at
            """,
            (self.profile_id, *params),
        )
        return [self._row_to_deadline(row) for row in rows]

    def due(self, now: datetime) -> list[Deadline]:
        """Сроки, по которым пора написать: время напоминания настало."""
        return self._active("d.remind_at <= ?", (to_utc(now, self.tz),))

    def not_yet_sent(self, now: datetime) -> list[Deadline]:
        """Из наступивших — те, о которых ещё ни разу не напоминали."""
        return self._active("d.remind_at <= ? AND d.sent_count = 0", (to_utc(now, self.tz),))

    def overdue(self, now: datetime) -> list[Deadline]:
        """Уже напоминали, срок прошёл, реакции не было."""
        return self._active("d.due_at < ? AND d.sent_count > 0", (to_utc(now, self.tz),))

    def on_day(self, day: datetime) -> list[Deadline]:
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self._active(
            "d.due_at >= ? AND d.due_at < ?", (to_utc(start, self.tz), to_utc(end, self.tz))
        )

    def counts(self, now: datetime) -> tuple[int, int]:
        """Просрочено и на сегодня — для закреплённого счётчика."""
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        overdue = self._active("d.due_at < ?", (to_utc(today_start, self.tz),))
        today = self.on_day(now)
        return len(overdue), len(today)

    # -- изменения ------------------------------------------------------

    def _edit(self, record_id: int, field: str, old: str | None, new: str | None, source: str = "user") -> None:
        self.db.execute(
            """
            INSERT INTO record_edits (record_id, edited_at, field, old_value, new_value, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record_id, utc_now_iso(), field, old, new, source),
        )

    def mark_sent(self, record_id: int) -> None:
        self.db.execute(
            "UPDATE deadlines SET sent_count = sent_count + 1 WHERE record_id = ?", (record_id,)
        )

    def snooze(self, record_id: int, until: datetime) -> Deadline | None:
        """Перенос напоминания. Событие остаётся на месте, двигается только remind_at."""
        current = self.get(record_id)
        if current is None or current.state != "active":
            return None
        self.db.execute(
            """
            UPDATE deadlines
               SET remind_at = ?, snooze_count = snooze_count + 1, sent_count = 0
             WHERE record_id = ?
            """,
            (to_utc(until, self.tz), record_id),
        )
        self._edit(record_id, "remind_at", str(current.remind_at), str(until))
        return self.get(record_id)

    def close(self, record_id: int, *, done_at: datetime, source: str = "user") -> int | None:
        """Закрывает срок. Повторяющийся порождает следующий и возвращает его id.

        Повторное нажатие той же кнопки второго действия не создаёт: запись
        уже не активна, и метод молча возвращает None.
        """
        current = self.get(record_id)
        if current is None or current.state != "active":
            return None

        self.db.execute(
            "UPDATE deadlines SET closed_at = ? WHERE record_id = ?",
            (to_utc(done_at, self.tz), record_id),
        )
        self.db.execute("UPDATE records SET state = 'done' WHERE id = ?", (record_id,))
        self._edit(record_id, "state", "active", "done", source)

        nxt = next_occurrence(current.due_at, current.repeat_rule, current.repeat_base, closed_at=done_at)
        if nxt is None:
            return None
        shift = current.due_at - current.remind_at
        new_id = self.create(
            title=current.title,
            due_at=nxt,
            remind_at=nxt - shift,
            category=current.category,
            repeat_rule=current.repeat_rule,
            repeat_base=current.repeat_base,
        )
        self.db.execute(
            "INSERT INTO links (from_id, to_id, kind, created_at) VALUES (?, ?, 'repeat_of', ?)",
            (new_id, record_id, utc_now_iso()),
        )
        return new_id

    def stop(self, record_id: int) -> bool:
        """«Не напоминать»: запись уходит из выдачи, но сделанной не считается."""
        current = self.get(record_id)
        if current is None or current.state != "active":
            return False
        self.db.execute("UPDATE records SET state = 'archived' WHERE id = ?", (record_id,))
        self._edit(record_id, "state", "active", "archived")
        return True
