"""Рассылка: напоминания, список просроченного, счётчик, тихие часы."""

from datetime import datetime, timedelta

from life_bot.db import Database
from life_bot.deadlines import Deadlines
from life_bot.reminders import Reminders
from tests.fakes import FakeBot

NOW = datetime(2026, 9, 9, 15, 0)
NIGHT = datetime(2026, 9, 10, 3, 0)


def build(db: Database):
    bot = FakeBot()
    deadlines = Deadlines(db, tz="Europe/Moscow")
    return bot, deadlines, Reminders(bot=bot, db=db, deadlines=deadlines, chat_id=100, tz="Europe/Moscow")


async def test_due_reminder_is_a_new_message_with_buttons(db: Database):
    """Сценарий 6: срок наступил — пришло напоминание."""
    bot, deadlines, reminders = build(db)
    deadlines.create(title="ОСАГО", due_at=NOW - timedelta(minutes=1))

    assert len(await reminders.send_due(NOW)) == 1
    chat_id, text, has_buttons = bot.sent[0]
    assert (chat_id, text, has_buttons) == (100, "ОСАГО.", True)


async def test_the_same_reminder_is_not_sent_twice(db: Database):
    bot, deadlines, reminders = build(db)
    deadlines.create(title="ОСАГО", due_at=NOW - timedelta(minutes=1))
    await reminders.send_due(NOW)
    await reminders.send_due(NOW + timedelta(minutes=1))
    assert bot.texts.count("ОСАГО.") == 1


async def test_nothing_is_sent_at_night(db: Database):
    """Сценарий 6: ночью бот молчит."""
    bot, deadlines, reminders = build(db)
    deadlines.create(title="ОСАГО", due_at=NIGHT - timedelta(hours=1))
    assert await reminders.send_due(NIGHT) == []
    assert bot.sent == []


async def test_what_was_missed_at_night_goes_out_in_the_morning(db: Database):
    bot, deadlines, reminders = build(db)
    deadlines.create(title="ОСАГО", due_at=NIGHT - timedelta(hours=1))
    await reminders.send_due(NIGHT)
    assert len(await reminders.send_due(NIGHT.replace(hour=9))) == 1


async def test_six_overdue_come_as_one_message(db: Database):
    """Сценарий 7: шесть просроченных — одно сообщение списком, а не шесть."""
    bot, deadlines, reminders = build(db)
    for i in range(6):
        record_id = deadlines.create(title=f"дело {i}", due_at=NOW - timedelta(days=2))
        deadlines.mark_sent(record_id)

    assert await reminders.send_overdue(NOW) is True
    assert len(bot.sent) == 2                      # список и счётчик
    text = bot.sent[0][1]
    assert text.startswith("Просрочено:")
    assert text.count("\n") == 6                   # заголовок плюс шесть строк


async def test_the_overdue_list_is_edited_not_reposted(db: Database):
    """Список обновляется на месте, дубли не плодятся."""
    bot, deadlines, reminders = build(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=2))
    deadlines.mark_sent(record_id)

    await reminders.send_overdue(NOW)
    sent_after_first = len(bot.sent)
    await reminders.send_overdue(NOW + timedelta(hours=10))     # текст тот же

    assert len(bot.sent) == sent_after_first        # нового сообщения не появилось


async def test_a_single_overdue_item_is_counted_in_words(db: Database):
    bot, deadlines, reminders = build(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=3))
    deadlines.mark_sent(record_id)
    deadlines.mark_sent(record_id)
    deadlines.mark_sent(record_id)

    await reminders.send_overdue(NOW)
    assert bot.sent[0][1] == "ОСАГО — третий день, четвёртое напоминание."


async def test_overdue_is_silent_at_night(db: Database):
    bot, deadlines, reminders = build(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NIGHT - timedelta(days=2))
    deadlines.mark_sent(record_id)
    assert await reminders.send_overdue(NIGHT) is False


async def test_counter_is_pinned_once_then_edited(db: Database):
    bot, deadlines, reminders = build(db)
    deadlines.create(title="вчера", due_at=NOW - timedelta(days=1))

    assert await reminders.update_counter(NOW) == "Просрочено 1"
    assert len(bot.pinned) == 1
    pinned_id = bot.pinned[0]

    deadlines.create(title="сегодня", due_at=NOW.replace(hour=20))
    assert await reminders.update_counter(NOW) == "Просрочено 1 · Сегодня 1"
    assert len(bot.sent) == 1                        # второго сообщения нет
    assert bot.edited[-1][0] == pinned_id


async def test_counter_says_clean_when_there_is_nothing(db: Database):
    _, _, reminders = build(db)
    assert await reminders.update_counter(NOW) == "Чисто."


async def test_counter_counts_the_inbox(db: Database):
    _, _, reminders = build(db)
    db.save_raw(kind="text", tg_message_id=1, text="что-то неразобранное")
    assert await reminders.update_counter(NOW) == "Инбокс 1"


async def test_snooze_by_an_hour_at_half_past_eleven_lands_at_nine(db: Database):
    """Сценарий 8: перенос через час в 23:30 — напоминание в 09:00, а не ночью."""
    from life_bot import keyboards

    _, deadlines, reminders = build(db)
    late = datetime(2026, 9, 9, 23, 30)
    record_id = deadlines.create(title="ОСАГО", due_at=late)
    deadline = deadlines.get(record_id)

    until = reminders.snooze_until(deadline, keyboards.HOUR, late)
    assert until == datetime(2026, 9, 10, 9, 0)


async def test_snooze_to_tomorrow_lands_in_the_morning(db: Database):
    from life_bot import keyboards

    _, deadlines, reminders = build(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW)
    until = reminders.snooze_until(deadlines.get(record_id), keyboards.TOMORROW, NOW)
    assert until == datetime(2026, 9, 10, 9, 0)


async def test_no_reaction_means_a_repeat_in_the_evening_scenario_6(db: Database):
    """Сценарий 6: не отреагировал — пришло повторно в 19:00, но не ночью."""
    bot, deadlines, reminders = build(db)
    deadlines.create(title="оплатить интернет", due_at=NOW)

    await reminders.send_due(NOW)                       # 15:00, первое напоминание
    assert bot.texts.count("оплатить интернет.") == 1

    evening = NOW.replace(hour=19)
    assert await reminders.send_overdue(evening) is True
    assert bot.texts.count("оплатить интернет.") == 2   # повтор в слоте

    night = NOW.replace(hour=23) + timedelta(hours=4)   # 03:00 следующего дня
    assert await reminders.send_overdue(night) is False


async def test_a_snoozed_item_is_not_repeated(db: Database):
    """Перенесённое из просрочки уходит до нового срока."""
    bot, deadlines, reminders = build(db)
    record_id = deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=1))
    deadlines.mark_sent(record_id)
    deadlines.snooze(record_id, NOW + timedelta(days=1))

    assert await reminders.send_overdue(NOW.replace(hour=19)) is False
    assert "ОСАГО" not in " ".join(bot.texts)


async def test_todays_item_in_a_list_is_not_counted_in_days(db: Database):
    bot, deadlines, reminders = build(db)
    deadlines.mark_sent(deadlines.create(title="интернет", due_at=NOW - timedelta(hours=1)))
    deadlines.mark_sent(deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=1)))

    await reminders.send_overdue(NOW.replace(hour=19))
    assert bot.sent[0][1] == "Просрочено:\nОСАГО — 1 день.\nинтернет — сегодня."


async def test_a_pile_missed_during_downtime_comes_as_one_list(db: Database):
    """Бот стоял сутки — пропущенное уходит списком, а не пачкой сообщений."""
    bot, deadlines, reminders = build(db)
    for i in range(5):
        deadlines.create(title=f"дело {i}", due_at=NOW - timedelta(days=2))

    await reminders.send_due(NOW)
    lists = [text for text in bot.texts if text.startswith("Просрочено:")]
    assert len(lists) == 1
    assert "дело 4" in lists[0]
    assert not [text for text in bot.texts if text == "дело 0."]     # по одному не слали


async def test_a_single_missed_item_still_comes_on_its_own(db: Database):
    bot, deadlines, reminders = build(db)
    deadlines.create(title="ОСАГО", due_at=NOW - timedelta(days=2))
    await reminders.send_due(NOW)
    assert bot.texts[0] == "ОСАГО."


async def test_todays_due_items_are_not_swept_into_the_list(db: Database):
    bot, deadlines, reminders = build(db)
    for i in range(3):
        deadlines.create(title=f"сегодня {i}", due_at=NOW - timedelta(minutes=1))
    await reminders.send_due(NOW)
    assert [text for text in bot.texts if text.startswith("Просрочено:")] == []
    assert bot.texts.count("сегодня 0.") == 1


async def test_a_failed_send_is_not_recorded_as_delivered(db: Database):
    """Сбой сети не должен молча съесть список просроченного."""
    bot, deadlines, reminders = build(db)
    for i in range(2):
        deadlines.mark_sent(deadlines.create(title=f"дело {i}", due_at=NOW - timedelta(days=2)))

    async def broken_send(*args, **kwargs):
        raise RuntimeError("сеть отвалилась")

    bot.send_message = broken_send
    assert await reminders.send_overdue(NOW) is False
    assert reminders.setting("overdue_message_text") == ""      # ничего не запомнили

    del bot.send_message                                        # связь вернулась
    assert await reminders.send_overdue(NOW) is True


async def test_a_long_list_is_trimmed_to_fit_a_message(db: Database):
    bot, deadlines, reminders = build(db)
    for i in range(14):
        deadlines.mark_sent(deadlines.create(title=f"дело {i}", due_at=NOW - timedelta(days=2)))

    await reminders.send_overdue(NOW)
    text = bot.sent[0][1]
    assert text.endswith("И ещё 4.")
    assert len(text) < 4096
