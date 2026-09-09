"""Тексты: строки должны совпадать с docs/life_bot_replies.md дословно."""

from datetime import date, datetime

from life_bot import texts

TODAY = date(2026, 9, 9)     # среда


def test_deadline_confirmation():
    assert texts.confirm_deadline(
        title="ОСАГО",
        due_at=datetime(2026, 10, 15, 9, 0),
        remind_at=datetime(2026, 10, 15, 9, 0),
        today=TODAY,
    ) == "Напомню 15 октября (чт) — ОСАГО."


def test_confirmation_with_preparation():
    assert texts.confirm_deadline(
        title="ОСАГО",
        due_at=datetime(2026, 10, 15, 9, 0),
        remind_at=datetime(2026, 9, 15, 9, 0),
        today=TODAY,
    ) == "Напомню 15 сентября (вт). Событие 15 октября (чт)."


def test_repeating_confirmation():
    assert texts.confirm_deadline(
        title="ОСАГО",
        due_at=datetime(2026, 10, 15, 9, 0),
        remind_at=datetime(2026, 10, 15, 9, 0),
        today=TODAY,
        repeat_rule="yearly",
    ) == "Напомню 15 октября (чт), каждый год."


def test_confirmation_for_the_next_few_days():
    assert texts.confirm_deadline(
        title="забрать посылку",
        due_at=datetime(2026, 9, 10, 9, 0),
        remind_at=datetime(2026, 9, 10, 9, 0),
        today=TODAY,
    ) == "Напомню завтра — забрать посылку."


def test_counter():
    assert texts.counter(2, 1, 3) == "Просрочено 2 · Сегодня 1 · Инбокс 3"
    assert texts.counter(0, 0, 0) == "Чисто."
    assert texts.counter(0, 1, 0) == "Сегодня 1"


def test_reminder_is_just_the_title():
    assert texts.reminder("ОСАГО") == "ОСАГО."


def test_single_overdue_item_counts_in_words():
    assert texts.reminder_overdue("ОСАГО", 3, 4) == "ОСАГО — третий день, четвёртое напоминание."


def test_overdue_comes_as_one_list():
    assert texts.overdue_list([("ОСАГО", 3), ("Оплатить интернет", 1)]) == (
        "Просрочено:\n"
        "ОСАГО — 3 дня.\n"
        "Оплатить интернет — 1 день."
    )


def test_snooze_until_tomorrow():
    assert texts.snoozed("ОСАГО", datetime(2026, 9, 10, 9, 0), TODAY) == (
        "ОСАГО. Отложено на завтра, 10 сентября (чт)."
    )


def test_snooze_within_the_same_day_names_the_time():
    assert texts.snoozed("ОСАГО", datetime(2026, 9, 9, 16, 0), TODAY) == "ОСАГО. Отложено на сегодня, 9 сентября (ср)."


def test_moved_confirmation_repeats_the_weekday():
    assert texts.moved_to(datetime(2026, 10, 22, 9, 0), TODAY) == "Перенёс на 22 октября (чт)."


def test_closing_a_repeat_names_the_next_date():
    assert texts.closed("ОСАГО", datetime(2027, 10, 15, 9, 0), TODAY) == (
        "ОСАГО. Следующий 15 октября 2027 (пт)."
    )
    assert texts.closed("ОСАГО") == "ОСАГО. Закрыл."


def test_today_command():
    assert texts.today_list([], [], TODAY) == "На сегодня ничего."
    assert texts.today_list(["оплатить интернет"], [("ОСАГО", 3)], TODAY) == (
        "Сегодня (ср): оплатить интернет.\n"
        "Просрочено: ОСАГО, третий день."
    )


def test_weekday_question():
    assert texts.weekday_question([date(2026, 9, 11), date(2026, 9, 18)], TODAY) == (
        "Пятница — 11 или 18 сентября?"
    )


def test_repeat_words():
    assert texts.repeat_words("yearly") == "каждый год"
    assert texts.repeat_words("every:90d") == "каждые 90 дней"
    assert texts.repeat_words(None) == ""


def test_no_cheerful_words_in_what_the_user_sees():
    """Правило 7: никаких «готово», «отлично», эмодзи и восклицательных знаков."""
    rendered = [
        texts.NOT_UNDERSTOOD, texts.SAVED_AS_IS, texts.NOTHING_TODAY, texts.CLEAN,
        texts.WHEN_DONE,
        texts.counter(2, 1, 3), texts.counter(0, 0, 0),
        texts.reminder("ОСАГО"), texts.reminder_overdue("ОСАГО", 3, 4),
        texts.overdue_list([("ОСАГО", 3)]),
        texts.snoozed("ОСАГО", datetime(2026, 9, 10, 9, 0), TODAY),
        texts.moved_to(datetime(2026, 10, 22, 9, 0), TODAY),
        texts.closed("ОСАГО"), texts.closed("ОСАГО", datetime(2027, 10, 15, 9, 0), TODAY),
        texts.stopped("ОСАГО"),
        texts.today_list(["интернет"], [("ОСАГО", 3)], TODAY),
        texts.confirm_deadline(title="ОСАГО", due_at=datetime(2026, 10, 15, 9, 0),
                               remind_at=datetime(2026, 10, 15, 9, 0), today=TODAY),
        texts.weekday_question([date(2026, 9, 11), date(2026, 9, 18)], TODAY),
    ]
    for line in rendered:
        low = line.lower()
        assert "!" not in line, line
        for banned in ("готово", "отлично", "добавлено", "успешно", "супер"):
            assert banned not in low, line
        assert all(ord(ch) < 0x2100 for ch in line), line   # эмодзи


def test_confirmations_stay_short():
    """Правило 1: одна строка, ориентир — до десяти слов."""
    line = texts.confirm_deadline(title="ОСАГО", due_at=datetime(2026, 10, 15, 9, 0),
                                  remind_at=datetime(2026, 10, 15, 9, 0), today=TODAY)
    assert "\n" not in line
    assert len(line.split()) <= 10
