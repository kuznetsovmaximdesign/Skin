"""Тихие часы. Бот не пишет по своей инициативе, приём работает круглосуточно."""

from __future__ import annotations

from datetime import datetime, time, timedelta


def parse_hm(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))


def in_quiet(moment: datetime, quiet_from: str = "00:00", quiet_to: str = "09:00") -> bool:
    start, end = parse_hm(quiet_from), parse_hm(quiet_to)
    current = moment.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end      # промежуток через полночь


def shift_out_of_quiet(
    moment: datetime, quiet_from: str = "00:00", quiet_to: str = "09:00"
) -> datetime:
    """Двигает момент к концу тихих часов.

    Перенос «через час» в 23:30 попадает на 00:30 — значит, напоминание придёт
    в 09:00, а не ночью.
    """
    if not in_quiet(moment, quiet_from, quiet_to):
        return moment
    end = parse_hm(quiet_to)
    shifted = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if shifted <= moment:
        shifted += timedelta(days=1)
    return shifted


def parse_slots(value: str) -> list[time]:
    """`09:00,19:00` — когда напоминать о просроченном."""
    return [parse_hm(part.strip()) for part in value.split(",") if part.strip()]
