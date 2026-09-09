"""Тексты бота. Формулировки взяты из docs/life_bot_replies.md дословно.

Правила оттуда: одна строка, ориентир до десяти слов; повторяется только то,
что могло быть распознано неверно; даты словами с сокращённым днём недели;
никаких «готово», «отлично», эмодзи и восклицательных знаков.
"""

from __future__ import annotations

from datetime import date, datetime

from .dates import format_date, format_date_full, plural_days

# Порядковые числительные: «третий день», «четвёртое напоминание».
_ORDINAL_MASC = (
    "", "первый", "второй", "третий", "четвёртый", "пятый", "шестой", "седьмой",
    "восьмой", "девятый", "десятый", "одиннадцатый", "двенадцатый", "тринадцатый",
    "четырнадцатый", "пятнадцатый", "шестнадцатый", "семнадцатый", "восемнадцатый",
    "девятнадцатый", "двадцатый",
)
_ORDINAL_NEUT = tuple(
    word[:-2] + ("ое" if word.endswith("ый") else "ье") if word else "" for word in _ORDINAL_MASC
)
_REPEAT_WORDS = {
    "yearly": "каждый год",
    "monthly": "каждый месяц",
    "weekly": "каждую неделю",
    "daily": "каждый день",
}


def ordinal(n: int, gender: str = "m") -> str:
    table = _ORDINAL_MASC if gender == "m" else _ORDINAL_NEUT
    if 1 <= n < len(table):
        return table[n]
    if 20 < n < 30:
        return ("двадцать " + table[n - 20]) if n - 20 < len(table) else str(n)
    if 30 < n < 40:
        return ("тридцать " + table[n - 30]) if n - 30 < len(table) else str(n)
    return str(n)


def repeat_words(rule: str | None) -> str:
    if not rule:
        return ""
    if rule in _REPEAT_WORDS:
        return _REPEAT_WORDS[rule]
    if rule.startswith("every:") and rule.endswith("d"):
        return f"каждые {plural_days(int(rule[6:-1]))}"
    if rule.startswith("every:") and rule.endswith("m"):
        return f"каждые {rule[6:-1]} месяцев"
    return ""


# ---------------------------------------------------------------- подтверждения


def confirm_deadline(
    *, title: str, due_at: datetime, remind_at: datetime, today: date, repeat_rule: str | None = None
) -> str:
    """`Напомню 15 октября (чт) — ОСАГО.` и его варианты из таблицы подтверждений."""
    if remind_at.date() != due_at.date():
        return (
            f"Напомню {format_date(remind_at, today=today)}. "
            f"Событие {format_date_full(due_at, today=today)}."
        )
    when = format_date(due_at, today=today)
    if repeat_rule:
        return f"Напомню {when}, {repeat_words(repeat_rule)}."
    return f"Напомню {when} — {title}."


NOT_UNDERSTOOD = "Не понял, отложил."
SAVED_AS_IS = "Не разобрал, сохранил как есть."
NOTHING_TODAY = "На сегодня ничего."
CLEAN = "Чисто."


# ---------------------------------------------------------------- счётчик


def counter(overdue: int, today: int, inbox: int) -> str:
    """`Просрочено 2 · Сегодня 1 · Инбокс 3`, а когда пусто — `Чисто.`"""
    if not (overdue or today or inbox):
        return CLEAN
    parts = []
    if overdue:
        parts.append(f"Просрочено {overdue}")
    if today:
        parts.append(f"Сегодня {today}")
    if inbox:
        parts.append(f"Инбокс {inbox}")
    return " · ".join(parts)


# ---------------------------------------------------------------- напоминания


def reminder(title: str) -> str:
    """В момент срока — только название. Всё остальное на кнопках."""
    return f"{title}."


def reminder_overdue(title: str, days: int, sent_count: int) -> str:
    """`ОСАГО — третий день, четвёртое напоминание.`"""
    return f"{title} — {ordinal(days)} день, {ordinal(sent_count, 'n')} напоминание."


def overdue_list(items: list[tuple[str, int]]) -> str:
    """Всё просроченное одним сообщением, а не по одному.

    `Просрочено:` и дальше строки вида `ОСАГО — 3 дня.`
    """
    lines = ["Просрочено:"]
    for title, days in items:
        lines.append(f"{title} — сегодня." if days == 0 else f"{title} — {plural_days(days)}.")
    return "\n".join(lines)


def snoozed(title: str, until: datetime, today: date) -> str:
    """`ОСАГО. Отложено на завтра, 10 сентября (чт).`"""
    word = format_date(until, today=today)
    if word in ("сегодня", "завтра"):
        return f"{title}. Отложено на {word}, {format_date_full(until, today=today)}."
    if until.date() == today:
        return f"{title}. Отложено на {until:%H:%M}."
    return f"{title}. Отложено на {word}."


def moved_to(until: datetime, today: date) -> str:
    """`Перенёс на 22 октября (чт).` — подтверждение переноса списком."""
    return f"Перенёс на {format_date_full(until, today=today)}."


def closed(title: str, next_due: datetime | None = None, today: date | None = None) -> str:
    """После «сделал» сообщение переписывается в результат, кнопки исчезают."""
    if next_due is not None and today is not None:
        return f"{title}. Следующий {format_date_full(next_due, today=today)}."
    return f"{title}. Закрыл."


def stopped(title: str) -> str:
    return f"{title}. Больше не напоминаю."


WHEN_DONE = "Когда сделал?"


# ---------------------------------------------------------------- команды


def today_list(items: list[str], overdue: list[tuple[str, int]], today: date) -> str:
    """`Сегодня (ср): оплатить интернет.` плюс строка просрочки, если она есть."""
    from .dates import WEEKDAYS_SHORT

    lines: list[str] = []
    if items:
        lines.append(f"Сегодня ({WEEKDAYS_SHORT[today.weekday()]}): {', '.join(items)}.")
    if overdue:
        parts = [f"{title}, {ordinal(days)} день" for title, days in overdue]
        lines.append(f"Просрочено: {'; '.join(parts)}.")
    return "\n".join(lines) if lines else NOTHING_TODAY


def weekday_question(options: list[date], today: date) -> str:
    """`Пятница — 11 или 18 сентября?`"""
    from .dates import MONTHS_GENITIVE, WEEKDAY_NAMES

    name = next(
        (word for word, index in WEEKDAY_NAMES.items() if index == options[0].weekday()), ""
    )
    if len(options) == 2 and options[0].month == options[1].month:
        return (
            f"{name.capitalize()} — {options[0].day} или "
            f"{options[1].day} {MONTHS_GENITIVE[options[1].month - 1]}?"
        )
    listed = " или ".join(format_date_full(day, today=today) for day in options)
    return f"{name.capitalize()} — {listed}?"
