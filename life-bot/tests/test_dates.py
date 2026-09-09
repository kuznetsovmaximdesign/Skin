"""Даты: вывод словами и разбор русских фраз."""

from datetime import date, datetime, timedelta

import pytest

from life_bot.dates import (
    clean_title,
    extract_lead,
    extract_repeat,
    extract_time,
    format_date,
    format_date_full,
    parse_when,
    plural_days,
    weekday_ambiguity,
)

TODAY = date(2026, 9, 9)          # среда
NOW = datetime(2026, 9, 9, 15, 0)


# ------------------------------------------------------------------ вывод


def test_today_and_tomorrow_are_words_without_weekday():
    assert format_date(TODAY, today=TODAY) == "сегодня"
    assert format_date(TODAY + timedelta(days=1), today=TODAY) == "завтра"


def test_date_carries_a_short_weekday():
    assert format_date(date(2026, 10, 15), today=TODAY) == "15 октября (чт)"
    assert format_date(date(2026, 9, 15), today=TODAY) == "15 сентября (вт)"
    assert format_date(date(2026, 11, 30), today=TODAY) == "30 ноября (пн)"


def test_year_named_only_when_it_is_not_the_current_one():
    assert format_date(date(2026, 12, 31), today=TODAY) == "31 декабря (чт)"
    assert format_date(date(2027, 1, 15), today=TODAY) == "15 января 2027 (пт)"


def test_full_form_never_says_today():
    assert format_date_full(TODAY, today=TODAY) == "9 сентября (ср)"


@pytest.mark.parametrize(
    "n,expected", [(1, "1 день"), (2, "2 дня"), (3, "3 дня"), (5, "5 дней"),
                   (11, "11 дней"), (21, "21 день"), (22, "22 дня"), (25, "25 дней")]
)
def test_days_are_declined(n, expected):
    assert plural_days(n) == expected


# ------------------------------------------------------------------ куски разбора


def test_repeat_calendar_and_from_fact():
    assert extract_repeat("каждый год 15 октября")[:2] == ("yearly", "calendar")
    assert extract_repeat("каждый месяц оплата")[:2] == ("monthly", "calendar")
    assert extract_repeat("каждые 90 дней фильтр")[:2] == ("every:90d", "done")
    assert extract_repeat("каждые 2 недели полив")[:2] == ("every:14d", "done")
    assert extract_repeat("просто дело")[:2] == (None, "calendar")


def test_repeat_is_cut_out_of_the_phrase():
    _, _, rest = extract_repeat("каждые 90 дней менять фильтр")
    assert "90" not in rest and "фильтр" in rest


def test_lead_time():
    assert extract_lead("напомни за месяц")[0] == timedelta(days=30)
    assert extract_lead("за неделю до")[0] == timedelta(days=7)
    assert extract_lead("за 3 дня")[0] == timedelta(days=3)
    assert extract_lead("без подготовки")[0] is None


def test_time_of_day():
    assert extract_time("в 18:00")[0] == (18, 0)
    assert extract_time("в 9 утра")[0] == (9, 0)
    assert extract_time("в 9 вечера")[0] == (21, 0)
    assert extract_time("в 12 дня")[0] == (12, 0)
    assert extract_time("без времени")[0] is None


def test_weekday_ambiguity_only_without_a_qualifier():
    assert weekday_ambiguity("напомни в пятницу") == "weekday"
    assert weekday_ambiguity("в эту пятницу") is None
    assert weekday_ambiguity("в ближайшую пятницу") is None
    assert weekday_ambiguity("в следующий вторник") is None
    assert weekday_ambiguity("купить молоко") is None


def test_title_loses_command_words():
    assert clean_title("напомни про ОСАГО") == "ОСАГО"
    assert clean_title("  про  оплатить интернет ") == "оплатить интернет"
    assert clean_title("забрать посылку") == "забрать посылку"


# ------------------------------------------------------------------ разбор целиком


def test_explicit_date_scenario_4():
    when = parse_when("Напомни 15 октября про ОСАГО", NOW)
    assert when.due_at.date() == date(2026, 10, 15)
    assert when.remind_at == when.due_at
    assert when.title == "ОСАГО"
    assert when.ambiguous == ()
    assert format_date(when.due_at, today=TODAY) == "15 октября (чт)"


def test_bare_weekday_is_a_question_not_a_guess_scenario_5():
    when = parse_when("напомни в пятницу", NOW)
    assert "weekday" in when.ambiguous
    assert when.alternatives == (date(2026, 9, 11), date(2026, 9, 18))


def test_qualified_weekday_asks_nothing():
    assert parse_when("напомни в эту пятницу", NOW).ambiguous == ()


def test_preparation_shifts_only_the_reminder():
    when = parse_when("напомни за месяц до 15 октября про ОСАГО", NOW)
    assert when.due_at.date() == date(2026, 10, 15)
    assert when.remind_at.date() == date(2026, 9, 15)


def test_relative_forms_keep_their_time():
    assert parse_when("через час", NOW).due_at == datetime(2026, 9, 9, 16, 0)
    assert parse_when("через 10 минут", NOW).due_at == datetime(2026, 9, 9, 15, 10)
    assert parse_when("через три недели", NOW).due_at.date() == date(2026, 9, 30)


def test_tomorrow_with_a_spoken_time():
    when = parse_when("завтра в 10 утра забрать посылку", NOW)
    assert when.due_at == datetime(2026, 9, 10, 10, 0)
    assert "посылку" in when.title


def test_date_without_time_lands_on_nine_in_the_morning():
    assert parse_when("15 октября ОСАГО", NOW).due_at == datetime(2026, 10, 15, 9, 0)


def test_numeric_forms_dateparser_misses():
    assert parse_when("15.10 техосмотр", NOW).due_at.date() == date(2026, 10, 15)
    assert parse_when("15.10.2027 техосмотр", NOW).due_at.date() == date(2027, 10, 15)
    assert parse_when("оплатить интернет 20 числа", NOW).due_at.date() == date(2026, 9, 20)


def test_passed_date_moves_to_next_year_and_says_so():
    when = parse_when("3 января подарок", NOW)
    assert when.due_at.date() == date(2027, 1, 3)
    assert "year" in when.ambiguous


def test_yearly_repeat():
    when = parse_when("каждый год 15 октября ОСАГО", NOW)
    assert (when.repeat_rule, when.repeat_base) == ("yearly", "calendar")
    assert when.due_at.date() == date(2026, 10, 15)
    assert when.title == "ОСАГО"


def test_interval_repeat_is_counted_from_the_fact():
    when = parse_when("каждые 90 дней менять фильтр", NOW)
    assert (when.repeat_rule, when.repeat_base) == ("every:90d", "done")
    assert "фильтр" in when.title


def test_phrase_without_a_date_returns_nothing():
    assert parse_when("купить молоко хлеб творог", NOW) is None
    assert parse_when("телефон подрядчика Сергей", NOW) is None
