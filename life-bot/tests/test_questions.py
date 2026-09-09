"""Висящие уточнения: ровно одно открытое, сутки жизни."""

from datetime import datetime, timedelta

from life_bot.db import Database
from life_bot.questions import Questions

NOW = datetime(2026, 9, 9, 15, 0)


def make(db: Database) -> Questions:
    return Questions(db, tz="Europe/Moscow")


def test_ask_and_read_back(db: Database):
    questions = make(db)
    raw_id = db.save_raw(kind="text", tg_message_id=1, text="напомни в пятницу")
    question_id = questions.ask(
        raw_id=raw_id, field="due_at", question="Пятница — 11 или 18 сентября?",
        options=["2026-09-11", "2026-09-18"], now=NOW,
    )
    row = questions.open()
    assert row["id"] == question_id
    assert row["field"] == "due_at"
    assert questions.options(question_id) == ["2026-09-11", "2026-09-18"]


def test_only_the_first_open_question_is_served(db: Database):
    questions = make(db)
    raw_id = db.save_raw(kind="text", tg_message_id=1, text="раз")
    first = questions.ask(raw_id=raw_id, field="due_at", question="первый?", options=[], now=NOW)
    questions.ask(raw_id=raw_id, field="due_at", question="второй?", options=[], now=NOW)
    assert questions.open()["id"] == first


def test_closing_twice_returns_false(db: Database):
    questions = make(db)
    raw_id = db.save_raw(kind="text", tg_message_id=1, text="раз")
    question_id = questions.ask(raw_id=raw_id, field="due_at", question="?", options=[], now=NOW)
    assert questions.close(question_id) is True
    assert questions.close(question_id) is False
    assert questions.open() is None


def test_a_day_without_an_answer_closes_it(db: Database):
    questions = make(db)
    raw_id = db.save_raw(kind="text", tg_message_id=1, text="раз")
    question_id = questions.ask(raw_id=raw_id, field="due_at", question="?", options=[], now=NOW)

    assert questions.expire(NOW + timedelta(hours=23)) == []
    assert questions.expire(NOW + timedelta(hours=25)) == [question_id]
    assert questions.get(question_id)["state"] == "expired"
