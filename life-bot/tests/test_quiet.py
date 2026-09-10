"""Тихие часы: бот не пишет с полуночи до девяти."""

from datetime import datetime, time

from life_bot.quiet import in_quiet, parse_slots, shift_out_of_quiet


def test_night_is_quiet():
    assert in_quiet(datetime(2026, 9, 10, 3, 0))
    assert in_quiet(datetime(2026, 9, 10, 0, 0))
    assert in_quiet(datetime(2026, 9, 10, 8, 59))


def test_day_is_not():
    assert not in_quiet(datetime(2026, 9, 10, 9, 0))
    assert not in_quiet(datetime(2026, 9, 9, 23, 59))


def test_shift_lands_on_the_edge():
    assert shift_out_of_quiet(datetime(2026, 9, 10, 0, 30)) == datetime(2026, 9, 10, 9, 0)
    assert shift_out_of_quiet(datetime(2026, 9, 10, 8, 59)) == datetime(2026, 9, 10, 9, 0)


def test_daytime_is_left_alone():
    moment = datetime(2026, 9, 9, 15, 0)
    assert shift_out_of_quiet(moment) == moment


def test_window_across_midnight():
    assert in_quiet(datetime(2026, 9, 9, 23, 30), "23:00", "07:00")
    assert shift_out_of_quiet(datetime(2026, 9, 9, 23, 30), "23:00", "07:00") == datetime(2026, 9, 10, 7, 0)


def test_slots_are_read_from_settings():
    assert parse_slots("09:00,19:00") == [time(9, 0), time(19, 0)]
    assert parse_slots(" 09:00 , 19:30 ") == [time(9, 0), time(19, 30)]
