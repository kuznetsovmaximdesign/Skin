"""Сообщение целиком: от текста до записи, кнопки и их повторные нажатия."""

from datetime import date, datetime, timedelta

import pytest

from life_bot import keyboards
from life_bot.db import Database
from life_bot.deadlines import Deadlines
from life_bot.intake import Intake
from life_bot.questions import Questions
from life_bot.reminders import Reminders
from life_bot.router import Handlers
from tests.fakes import FakeBot, FakeCallback, FakeMessage

NOW = datetime(2026, 9, 9, 15, 0)      # среда


@pytest.fixture()
def flow(db: Database, tmp_path):
    bot = FakeBot()
    deadlines = Deadlines(db, tz="Europe/Moscow")
    reminders = Reminders(bot=bot, db=db, deadlines=deadlines, chat_id=100, tz="Europe/Moscow")
    handlers = Handlers(
        db=db,
        intake=Intake(db, tmp_path / "files"),
        deadlines=deadlines,
        questions=Questions(db, tz="Europe/Moscow"),
        reminders=reminders,
        clock=lambda: NOW,
    )
    return handlers, bot, deadlines, db


# ------------------------------------------------------------------ приём фразы


async def test_explicit_date_becomes_a_deadline_scenario_4(flow):
    handlers, bot, deadlines, db = flow
    message = FakeMessage("Напомни 15 октября про ОСАГО")
    await handlers.on_message(message, bot)

    assert message.replies[0][0] == "Напомню 15 октября (чт) — ОСАГО."
    deadline = deadlines.due(datetime(2026, 10, 16, 9, 0))[0]
    assert (deadline.title, deadline.due_at.date()) == ("ОСАГО", date(2026, 10, 15))
    assert db.get_raw(1)["parse_state"] == "parsed"
    assert db.get_raw(1)["parser"] == "rules"


async def test_ambiguous_weekday_asks_instead_of_guessing_scenario_5(flow):
    handlers, bot, deadlines, db = flow
    message = FakeMessage("напомни в пятницу к врачу")
    await handlers.on_message(message, bot)

    text, markup = message.replies[0]
    assert text == "Пятница — 11 или 18 сентября?"
    assert markup is not None
    assert deadlines.due(NOW + timedelta(days=365)) == []      # записи ещё нет
    assert db.execute("SELECT state FROM pending_questions")[0]["state"] == "open"


async def test_answering_the_question_creates_the_record(flow):
    handlers, bot, deadlines, db = flow
    await handlers.on_message(FakeMessage("напомни в пятницу к врачу"), bot)
    question_id = db.execute("SELECT id FROM pending_questions")[0]["id"]

    callback = FakeCallback(f"{keyboards.WEEKDAY_PICK}:{question_id}:1")
    await handlers.on_callback(callback)

    assert callback.last_text == "Напомню 18 сентября (пт) — к врачу."
    assert callback.last_markup is None                        # кнопки исчезли
    assert deadlines.due(datetime(2026, 9, 19, 9, 0))[0].due_at.date() == date(2026, 9, 18)
    assert db.execute("SELECT state FROM pending_questions")[0]["state"] == "answered"


async def test_this_is_new_closes_the_question_without_a_record(flow):
    handlers, bot, deadlines, db = flow
    await handlers.on_message(FakeMessage("напомни в пятницу"), bot)
    question_id = db.execute("SELECT id FROM pending_questions")[0]["id"]

    callback = FakeCallback(f"{keyboards.WEEKDAY_NEW}:{question_id}")
    await handlers.on_callback(callback)

    assert callback.last_text == "Не понял, отложил."
    assert deadlines.due(NOW + timedelta(days=365)) == []


async def test_a_phrase_without_a_date_stays_in_the_inbox(flow):
    handlers, bot, deadlines, db = flow
    message = FakeMessage("телефон подрядчика по кровле, Сергей")
    await handlers.on_message(message, bot)

    assert message.replies[0][0] == "Не понял, отложил."   # молчать нельзя: непонятно, принято ли
    assert db.get_raw(1)["parse_state"] == "new"
    assert deadlines.due(NOW + timedelta(days=365)) == []


async def test_a_date_without_a_subject_is_a_question_not_a_guess(flow):
    handlers, bot, deadlines, db = flow
    first = FakeMessage("15 октября нужно напомнить в 19 ч")
    await handlers.on_message(first, bot)

    assert first.replies[0][0] == "О чём напомнить?"
    assert deadlines.due(NOW + timedelta(days=365)) == []

    second = FakeMessage("про стрижку", message_id=2)
    await handlers.on_message(second, bot)

    assert second.replies[0][0] == "Напомню 15 октября (чт) — про стрижку."
    deadline = deadlines.due(datetime(2026, 10, 16, 9, 0))[0]
    assert deadline.due_at == datetime(2026, 10, 15, 19, 0)
    assert db.execute("SELECT state FROM pending_questions")[0]["state"] == "answered"


async def test_the_answer_does_not_create_a_second_record(flow):
    handlers, bot, deadlines, db = flow
    await handlers.on_message(FakeMessage("15 октября напомнить в 19 ч"), bot)
    await handlers.on_message(FakeMessage("про стрижку", message_id=2), bot)
    assert len(db.execute("SELECT id FROM records")) == 1


async def test_repeating_phrase_is_confirmed_as_repeating(flow):
    handlers, bot, _, _ = flow
    message = FakeMessage("каждый год 15 октября ОСАГО")
    await handlers.on_message(message, bot)
    assert message.replies[0][0] == "Напомню 15 октября (чт), каждый год."


async def test_preparation_is_confirmed_with_both_dates(flow):
    handlers, bot, _, _ = flow
    message = FakeMessage("напомни за месяц до 15 октября про ОСАГО")
    await handlers.on_message(message, bot)
    assert message.replies[0][0] == "Напомню 15 сентября (вт). Событие 15 октября (чт)."


# ------------------------------------------------------------------ кнопки


async def test_done_closes_and_rewrites_the_message(flow):
    handlers, bot, deadlines, _ = flow
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)

    callback = FakeCallback(f"{keyboards.DONE}:{record_id}")
    await handlers.on_callback(callback)

    assert callback.last_text == "ОСАГО. Закрыл."
    assert callback.last_markup is None
    assert deadlines.get(record_id).state == "done"


async def test_pressing_done_twice_does_not_act_twice(flow):
    """Повторное нажатие той же кнопки не создаёт второе действие."""
    handlers, bot, deadlines, db = flow
    record_id = deadlines.create(title="ОСАГО", due_at=NOW, repeat_rule="yearly")

    await handlers.on_callback(FakeCallback(f"{keyboards.DONE}:{record_id}"))
    await handlers.on_callback(FakeCallback(f"{keyboards.DONE}:{record_id}"))

    assert len(db.execute("SELECT id FROM records WHERE type = 'deadline'")) == 2


async def test_overdue_by_days_asks_when_it_was_done_scenario_9(flow):
    handlers, bot, deadlines, db = flow
    record_id = deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=3))

    first = FakeCallback(f"{keyboards.DONE}:{record_id}")
    await handlers.on_callback(first)
    assert first.last_text == "Когда сделал?"
    assert first.last_markup is not None
    assert deadlines.get(record_id).state == "active"          # ещё не закрыт

    second = FakeCallback(f"{keyboards.DONE_YESTERDAY}:{record_id}")
    await handlers.on_callback(second)

    closed_at = db.execute("SELECT closed_at FROM deadlines WHERE record_id = ?", (record_id,))[0]
    from life_bot.dates import to_local

    assert to_local(closed_at["closed_at"], "Europe/Moscow").date() == date(2026, 9, 8)


async def test_done_on_time_uses_the_original_date(flow):
    handlers, bot, deadlines, db = flow
    due = NOW - timedelta(days=3)
    record_id = deadlines.create(title="ОСАГО", due_at=due)

    await handlers.on_callback(FakeCallback(f"{keyboards.DONE}:{record_id}"))
    await handlers.on_callback(FakeCallback(f"{keyboards.DONE_ONTIME}:{record_id}"))

    from life_bot.dates import to_local

    closed_at = db.execute("SELECT closed_at FROM deadlines WHERE record_id = ?", (record_id,))[0]
    assert to_local(closed_at["closed_at"], "Europe/Moscow").date() == due.date()


async def test_closing_a_repeat_names_the_next_date(flow):
    handlers, bot, deadlines, _ = flow
    record_id = deadlines.create(
        title="ОСАГО", due_at=datetime(2026, 9, 9, 9, 0), repeat_rule="yearly"
    )
    callback = FakeCallback(f"{keyboards.DONE}:{record_id}")
    await handlers.on_callback(callback)
    assert callback.last_text == "ОСАГО. Следующий 9 сентября 2027 (чт)."


async def test_stop_hides_it_without_calling_it_done(flow):
    handlers, bot, deadlines, _ = flow
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    callback = FakeCallback(f"{keyboards.STOP}:{record_id}")
    await handlers.on_callback(callback)

    assert callback.last_text == "ОСАГО. Больше не напоминаю."
    assert deadlines.get(record_id).state == "archived"


async def test_snooze_to_tomorrow_is_confirmed_with_the_weekday(flow):
    handlers, bot, deadlines, _ = flow
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    callback = FakeCallback(f"{keyboards.TOMORROW}:{record_id}")
    await handlers.on_callback(callback)

    assert callback.last_text == "ОСАГО. Отложено на завтра, 10 сентября (чт)."
    assert deadlines.get(record_id).remind_at == datetime(2026, 9, 10, 9, 0)


async def test_all_overdue_move_together(flow):
    handlers, bot, deadlines, _ = flow
    ids = []
    for i in range(3):
        record_id = deadlines.create(title=f"дело {i}", due_at=NOW - timedelta(days=2))
        deadlines.mark_sent(record_id)
        ids.append(record_id)

    callback = FakeCallback(f"{keyboards.ALL_TOMORROW}:0")
    await handlers.on_callback(callback)

    assert callback.last_text == "Перенёс на 10 сентября (чт)."
    for record_id in ids:
        assert deadlines.get(record_id).remind_at == datetime(2026, 9, 10, 9, 0)


async def test_a_button_for_a_missing_record_is_harmless(flow):
    handlers, bot, _, _ = flow
    callback = FakeCallback(f"{keyboards.DONE}:999")
    await handlers.on_callback(callback)
    assert callback.answered == 1
    assert callback.edits == []
