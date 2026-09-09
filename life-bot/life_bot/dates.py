"""Даты: разбор русских фраз и вывод словами.

Разбор дат делает dateparser — своего парсера тут нет. Правилами добираются
только те конструкции, где библиотека ошибается или молчит: повторы, подготовка
(«напомни за месяц»), время суток словами и числовые формы вроде «15.10».
Порядок важен: сначала из фразы вырезается всё это, а остаток отдаётся
dateparser — иначе «каждые 90 дней» он принимает за дату в декабре.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

warnings.filterwarnings("ignore", module="dateparser")

MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKDAY_NAMES = {
    "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
    "пятница": 4, "суббота": 5, "воскресенье": 6,
}

DEFAULT_HOUR = 9  # дата без времени: напоминаем в 09:00, сразу после тихих часов

# Слова, после которых день недели перестаёт быть неоднозначным.
WEEKDAY_QUALIFIERS = ("эт", "ближайш", "следующ", "будущ", "текущ")

_COMMAND_WORDS = re.compile(
    r"^\s*(напомни(ть)?|напомнить|не\s+забыть|надо|нужно|запиши|поставь)\b\s*", re.I
)
_LEADING_JUNK = re.compile(r"^\s*(?:(?:про|о|об|обо|что|чтобы|это)\b\s+|[,.—:-]+\s*)", re.I)


@dataclass(frozen=True)
class When:
    """Разобранный срок. Время локальное, наивное — в UTC переводится выше."""

    due_at: datetime
    remind_at: datetime
    title: str = ""
    repeat_rule: str | None = None
    repeat_base: str = "calendar"
    ambiguous: tuple[str, ...] = ()
    matched: str = ""
    alternatives: tuple[date, ...] = field(default=())


# ---------------------------------------------------------------- вывод


def format_date(value: date | datetime, *, today: date) -> str:
    """`15 октября (чт)`, `сегодня`, `завтра`. Год — только если не текущий."""
    day = value.date() if isinstance(value, datetime) else value
    if day == today:
        return "сегодня"
    if day == today + timedelta(days=1):
        return "завтра"
    text = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    if day.year != today.year:
        text += f" {day.year}"
    return f"{text} ({WEEKDAYS_SHORT[day.weekday()]})"


def format_date_full(value: date | datetime, *, today: date) -> str:
    """То же, но без «сегодня» и «завтра» — когда нужна именно дата."""
    day = value.date() if isinstance(value, datetime) else value
    text = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    if day.year != today.year:
        text += f" {day.year}"
    return f"{text} ({WEEKDAYS_SHORT[day.weekday()]})"


def plural_days(n: int) -> str:
    """`1 день`, `3 дня`, `5 дней` — для строк о просрочке."""
    if 11 <= n % 100 <= 14:
        return f"{n} дней"
    last = n % 10
    if last == 1:
        return f"{n} день"
    if last in (2, 3, 4):
        return f"{n} дня"
    return f"{n} дней"


# ---------------------------------------------------------------- разбор


_REPEAT_PATTERNS = (
    (re.compile(r"\b(кажд(ый|ые)\s+год|ежегодно|раз\s+в\s+год)\b", re.I), "yearly", "calendar"),
    (re.compile(r"\b(кажд(ый|ые)\s+месяц|ежемесячно|раз\s+в\s+месяц)\b", re.I), "monthly", "calendar"),
    (re.compile(r"\b(кажд(ую|ые)\s+недел[юи]|еженедельно|раз\s+в\s+недел[юю])\b", re.I), "weekly", "calendar"),
    (re.compile(r"\b(кажд(ый|ые)\s+день|ежедневно)\b", re.I), "daily", "calendar"),
)
_REPEAT_EVERY_N = re.compile(r"\bкажд(?:ые|ый)\s+(\d+)\s*(дн\w*|недел\w*|месяц\w*)", re.I)


def extract_repeat(text: str) -> tuple[str | None, str, str]:
    """Возвращает (правило, база, текст без правила).

    База `calendar` — жёсткая дата: пропуск график не двигает. База `done` —
    интервал отсчитывается от фактического закрытия. «Каждый год» — календарь,
    «каждые 90 дней» — от факта: так это и звучит по-русски.
    """
    match = _REPEAT_EVERY_N.search(text)
    if match:
        number, unit = int(match.group(1)), match.group(2).lower()
        if unit.startswith("недел"):
            rule = f"every:{number * 7}d"
        elif unit.startswith("месяц"):
            rule = f"every:{number}m"
        else:
            rule = f"every:{number}d"
        return rule, "done", _cut(text, match.span())

    for pattern, rule, base in _REPEAT_PATTERNS:
        match = pattern.search(text)
        if match:
            return rule, base, _cut(text, match.span())
    return None, "calendar", text


_LEAD = re.compile(r"\bза\s+(\d+|один|одну|два|две|три|четыре|пять|месяц|недел\w+|день|дня|дней)\s*(дн\w*|недел\w*|месяц\w*)?\b", re.I)
_WORD_NUMBERS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}


def extract_lead(text: str) -> tuple[timedelta | None, str]:
    """«напомни за месяц» — сдвигает напоминание, событие остаётся на месте."""
    match = _LEAD.search(text)
    if not match:
        return None, text
    head, unit = match.group(1).lower(), (match.group(2) or "").lower()
    if head in ("месяц",):
        delta = timedelta(days=30)
    elif head.startswith("недел"):
        delta = timedelta(days=7)
    elif head in ("день", "дня", "дней"):
        delta = timedelta(days=1)
    else:
        number = _WORD_NUMBERS.get(head, int(head) if head.isdigit() else None)
        if number is None:
            return None, text
        if unit.startswith("недел"):
            delta = timedelta(days=7 * number)
        elif unit.startswith("месяц"):
            delta = timedelta(days=30 * number)
        elif unit.startswith("дн"):
            delta = timedelta(days=number)
        else:
            return None, text
    return delta, _cut(text, match.span())


_TIME_HHMM = re.compile(r"\b(?:в|к)\s*([01]?\d|2[0-3])[:\-]([0-5]\d)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b", re.I)
_TIME_PART_OF_DAY = re.compile(r"\b(?:в|к)?\s*([01]?\d|2[0-3])\s+(утра|дня|вечера|ночи)\b", re.I)


def extract_time(text: str) -> tuple[tuple[int, int] | None, str]:
    """«в 18:00», «в 9 утра», «в 9 вечера». dateparser время суток словами не берёт."""
    match = _TIME_PART_OF_DAY.search(text)
    if match:
        hour, part = int(match.group(1)), match.group(2).lower()
        if part == "вечера" and hour < 12:
            hour += 12
        elif part == "дня" and hour < 12:
            hour = hour if hour == 12 else hour + 12
        elif part == "ночи" and hour == 12:
            hour = 0
        return (hour % 24, 0), _cut(text, match.span())

    match = _TIME_HHMM.search(text)
    if match:
        hour, minute = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        return (int(hour), int(minute)), _cut(text, match.span())
    return None, text


_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_DAY_OF_MONTH = re.compile(r"\b(\d{1,2})\s*(?:числа|-го)\b", re.I)


def extract_numeric_date(text: str, today: date) -> tuple[date | None, str, tuple[str, ...]]:
    """`15.10`, `15.10.2027`, `20 числа` — dateparser эти формы не разбирает."""
    match = _NUMERIC_DATE.search(text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        raw_year = match.group(3)
        ambiguous: tuple[str, ...] = ()
        if raw_year:
            year = int(raw_year)
            if year < 100:
                year += 2000
        else:
            year = today.year
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None, text, ()
            if candidate < today:
                year += 1
                ambiguous = ("year",)
        try:
            return date(year, month, day), _cut(text, match.span()), ambiguous
        except ValueError:
            return None, text, ()

    match = _DAY_OF_MONTH.search(text)
    if match:
        day = int(match.group(1))
        year, month = today.year, today.month
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None, text, ()
        if candidate < today:
            month += 1
            if month > 12:
                month, year = 1, year + 1
            candidate = date(year, month, day)
        return candidate, _cut(text, match.span()), ()
    return None, text, ()


_BARE_WEEKDAY = re.compile(
    r"\b(?:в|во)?\s*(понедельник|вторник|сред[уы]|четверг|пятниц[уы]|суббот[ыу]|воскресень[ея])\b", re.I
)


def weekday_ambiguity(text: str) -> str | None:
    """«в пятницу» без уточнения — какая именно? «в эту пятницу» — вопросов нет."""
    match = _BARE_WEEKDAY.search(text)
    if not match:
        return None
    before = text[: match.start()].lower()
    if any(word in before[-20:] for word in WEEKDAY_QUALIFIERS):
        return None
    return "weekday"


def _cut(text: str, span: tuple[int, int]) -> str:
    return (text[: span[0]] + " " + text[span[1] :]).strip()


def clean_title(text: str) -> str:
    """Остаток фразы после вырезания даты — это и есть название."""
    result = _COMMAND_WORDS.sub("", text.strip())
    previous = None
    while previous != result:
        previous = result
        result = _LEADING_JUNK.sub("", result).strip()
    result = re.sub(r"\s{2,}", " ", result).strip(" ,.—-:")
    return result


def _interval_of(rule: str) -> timedelta | None:
    """`every:90d` -> 90 дней, `every:3m` -> примерно три месяца."""
    match = re.fullmatch(r"every:(\d+)([dm])", rule)
    if not match:
        return None
    number, unit = int(match.group(1)), match.group(2)
    return timedelta(days=number * (30 if unit == "m" else 1))


def _has_any_date(text: str, now: datetime) -> bool:
    from dateparser.search import search_dates

    return bool(
        search_dates(
            text,
            languages=["ru"],
            settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now,
                      "DATE_ORDER": "DMY", "RETURN_AS_TIMEZONE_AWARE": False},
        )
    )


def parse_when(text: str, now: datetime) -> When | None:
    """Разбирает фразу в срок. Ничего не нашёл — None, догадок не строит."""
    from dateparser.search import search_dates

    today = now.date()
    rest = text
    repeat_rule, repeat_base, rest = extract_repeat(rest)
    lead, rest = extract_lead(rest)
    time_of_day, rest = extract_time(rest)
    ambiguous: list[str] = []

    day, rest_after_numeric, numeric_ambiguity = extract_numeric_date(rest, today)
    if day is None and repeat_rule and repeat_rule.startswith("every:"):
        interval = _interval_of(repeat_rule)
        if interval is not None and not _has_any_date(rest, now):
            due_at = now.replace(second=0, microsecond=0) + interval
            return When(
                due_at=due_at,
                remind_at=due_at - lead if lead else due_at,
                title=clean_title(rest),
                repeat_rule=repeat_rule,
                repeat_base=repeat_base,
                matched=repeat_rule,
            )
    matched = ""
    if day is not None:
        matched = rest[: len(rest) - len(rest_after_numeric)].strip() or "дата"
        rest = rest_after_numeric
        ambiguous.extend(numeric_ambiguity)
    else:
        found = search_dates(
            rest,
            languages=["ru"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now,
                "DATE_ORDER": "DMY",
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if not found:
            return None
        matched, parsed = found[0]
        rest = rest.replace(matched, " ", 1)
        day = parsed.date()
        # Относительная форма («через час») приносит своё время — его и берём.
        if time_of_day is None and (parsed.hour or parsed.minute):
            time_of_day = (parsed.hour, parsed.minute)
        if day.year != today.year and not re.search(r"\b(19|20)\d{2}\b", matched):
            ambiguous.append("year")

    weekday_flag = weekday_ambiguity(text)
    if weekday_flag:
        ambiguous.append(weekday_flag)

    hour, minute = time_of_day if time_of_day else (DEFAULT_HOUR, 0)
    due_at = datetime(day.year, day.month, day.day, hour, minute)
    remind_at = due_at - lead if lead else due_at

    alternatives: tuple[date, ...] = ()
    if weekday_flag:
        alternatives = (day, day + timedelta(days=7))

    return When(
        due_at=due_at,
        remind_at=remind_at,
        title=clean_title(rest),
        repeat_rule=repeat_rule,
        repeat_base=repeat_base,
        ambiguous=tuple(dict.fromkeys(ambiguous)),
        matched=matched.strip(),
        alternatives=alternatives,
    )


# ---------------------------------------------------------------- часовые пояса


def to_utc(local: datetime, tz: str) -> str:
    """Локальное наивное время -> строка UTC для базы."""
    from zoneinfo import ZoneInfo

    aware = local.replace(tzinfo=ZoneInfo(tz))
    return aware.astimezone(ZoneInfo("UTC")).replace(microsecond=0).isoformat()


def to_local(utc_iso: str, tz: str) -> datetime:
    """Строка UTC из базы -> локальное наивное время для показа."""
    from zoneinfo import ZoneInfo

    value = datetime.fromisoformat(utc_iso)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def now_local(tz: str) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(tz)).replace(tzinfo=None, microsecond=0)
