"""Сроки: создание, выдача, закрытие, перенос, повторы обоих видов."""

from datetime import date, datetime, timedelta

from life_bot.dates import parse_when, to_local
from life_bot.db import Database
from life_bot.deadlines import Deadlines, next_occurrence

NOW = datetime(2026, 9, 9, 15, 0)


def make(db: Database) -> Deadlines:
    return Deadlines(db, tz="Europe/Moscow")


# ------------------------------------------------------------------ повторы


def test_calendar_repeat_ignores_a_late_close():
    """Сценарий 10: календарный повтор закрыт с опозданием — дата не съехала."""
    due = datetime(2026, 10, 15, 9, 0)
    closed = datetime(2026, 10, 20, 12, 0)          # закрыл на пять дней позже
    assert next_occurrence(due, "yearly", "calendar", closed_at=closed) == datetime(2027, 10, 15, 9, 0)


def test_interval_repeat_counts_from_the_fact():
    """Сценарий 10: интервальный сдвинулся от факта закрытия."""
    due = datetime(2026, 10, 15, 9, 0)
    closed = datetime(2026, 10, 20, 12, 0)
    assert next_occurrence(due, "every:90d", "done", closed_at=closed) == datetime(2027, 1, 18, 12, 0)


def test_calendar_repeat_skips_past_periods():
    due = datetime(2024, 10, 15, 9, 0)
    closed = datetime(2026, 10, 20, 12, 0)
    assert next_occurrence(due, "yearly", "calendar", closed_at=closed).year == 2027


def test_monthly_and_weekly():
    due = datetime(2026, 1, 31, 9, 0)
    assert next_occurrence(due, "monthly", "calendar", closed_at=due).date() == date(2026, 2, 28)
    assert next_occurrence(due, "weekly", "calendar", closed_at=due).date() == date(2026, 2, 7)


def test_without_a_rule_there_is_no_next():
    assert next_occurrence(NOW, None, "calendar", closed_at=NOW) is None


# ------------------------------------------------------------------ создание и выдача


def test_create_stores_utc_and_reads_back_local(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=datetime(2026, 10, 15, 9, 0))

    stored = db.execute("SELECT due_at FROM deadlines WHERE record_id = ?", (record_id,))[0]["due_at"]
    assert stored == "2026-10-15T06:00:00+00:00"           # Москва +3
    assert deadlines.get(record_id).due_at == datetime(2026, 10, 15, 9, 0)


def test_record_and_deadline_are_one_fact(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    record = db.execute("SELECT * FROM records WHERE id = ?", (record_id,))[0]
    assert (record["type"], record["state"], record["profile_id"]) == ("deadline", "active", 1)


def test_create_from_a_parsed_phrase(db: Database):
    deadlines = make(db)
    when = parse_when("Напомни 15 октября про ОСАГО", NOW)
    deadline = deadlines.get(deadlines.create_from_when(when))
    assert deadline.title == "ОСАГО"
    assert deadline.due_at.date() == date(2026, 10, 15)


def test_due_and_overdue_are_different_questions(db: Database):
    deadlines = make(db)
    soon = deadlines.create(title="скоро", due_at=NOW + timedelta(hours=1))
    now_id = deadlines.create(title="пора", due_at=NOW - timedelta(minutes=1))

    assert [d.record_id for d in deadlines.due(NOW)] == [now_id]
    assert deadlines.overdue(NOW) == []          # ещё ни разу не напоминали
    deadlines.mark_sent(now_id)
    assert [d.record_id for d in deadlines.overdue(NOW)] == [now_id]
    assert soon not in [d.record_id for d in deadlines.due(NOW)]


def test_counts_for_the_pinned_message(db: Database):
    deadlines = make(db)
    deadlines.create(title="вчера", due_at=NOW - timedelta(days=1))
    deadlines.create(title="сегодня", due_at=NOW.replace(hour=20))
    deadlines.create(title="завтра", due_at=NOW + timedelta(days=1))
    assert deadlines.counts(NOW) == (1, 1)


# ------------------------------------------------------------------ закрытие и перенос


def test_close_moves_it_out_of_sight(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    assert deadlines.close(record_id, done_at=NOW) is None
    assert deadlines.get(record_id).state == "done"
    assert deadlines.due(NOW) == []


def test_closing_twice_does_nothing_the_second_time(db: Database):
    """Повторное нажатие той же кнопки не создаёт второе действие."""
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW, repeat_rule="yearly")
    first = deadlines.close(record_id, done_at=NOW)
    second = deadlines.close(record_id, done_at=NOW)
    assert first is not None and second is None
    assert len(db.execute("SELECT id FROM records WHERE type='deadline'")) == 2


def test_closing_a_repeat_creates_the_next_one_and_links_it(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(
        title="ОСАГО", due_at=datetime(2026, 10, 15, 9, 0), repeat_rule="yearly"
    )
    new_id = deadlines.close(record_id, done_at=datetime(2026, 10, 20, 12, 0))
    assert deadlines.get(new_id).due_at == datetime(2027, 10, 15, 9, 0)

    link = db.execute("SELECT * FROM links WHERE from_id = ?", (new_id,))[0]
    assert (link["to_id"], link["kind"]) == (record_id, "repeat_of")


def test_repeat_keeps_the_preparation_gap(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(
        title="ОСАГО",
        due_at=datetime(2026, 10, 15, 9, 0),
        remind_at=datetime(2026, 9, 15, 9, 0),      # за месяц
        repeat_rule="yearly",
    )
    new_id = deadlines.close(record_id, done_at=datetime(2026, 10, 15, 10, 0))
    nxt = deadlines.get(new_id)
    assert (nxt.due_at - nxt.remind_at).days == 30


def test_closed_yesterday_is_stored_as_yesterday(db: Database):
    """Сценарий 9: закрыл кнопкой «вчера» — в базе вчерашняя дата."""
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=3))
    yesterday = (NOW - timedelta(days=1)).replace(hour=12, minute=0)
    deadlines.close(record_id, done_at=yesterday)

    closed_at = db.execute("SELECT closed_at FROM deadlines WHERE record_id = ?", (record_id,))[0]["closed_at"]
    assert to_local(closed_at, "Europe/Moscow").date() == yesterday.date()


def test_snooze_moves_only_the_reminder(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=datetime(2026, 10, 15, 9, 0))
    deadlines.mark_sent(record_id)
    moved = deadlines.snooze(record_id, datetime(2026, 10, 22, 9, 0))

    assert moved.remind_at == datetime(2026, 10, 22, 9, 0)
    assert moved.due_at == datetime(2026, 10, 15, 9, 0)     # событие на месте
    assert moved.snooze_count == 1
    assert moved.sent_count == 0                            # напомнить заново


def test_stop_hides_it_without_calling_it_done(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    assert deadlines.stop(record_id) is True
    assert deadlines.get(record_id).state == "archived"
    assert deadlines.stop(record_id) is False               # второй раз — ничего


def test_every_change_is_written_down(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    deadlines.snooze(record_id, NOW + timedelta(days=1))
    deadlines.close(record_id, done_at=NOW)

    fields = [row["field"] for row in db.execute(
        "SELECT field FROM record_edits WHERE record_id = ? ORDER BY id", (record_id,))]
    assert fields == ["remind_at", "state"]


def test_days_overdue(db: Database):
    deadlines = make(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=3))
    assert deadlines.get(record_id).days_overdue(NOW) == 3
