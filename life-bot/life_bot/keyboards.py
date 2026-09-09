"""Кнопки. После нажатия сообщение переписывается в результат, кнопки исчезают."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# d — действие над одним сроком, o — над всем списком просроченного.
DONE = "d:done"
STOP = "d:stop"
HOUR = "d:hour"
TOMORROW = "d:tomorrow"
WEEK = "d:week"
WHEN = "d:when"
DONE_TODAY = "d:today"
DONE_YESTERDAY = "d:yesterday"
DONE_ONTIME = "d:ontime"
ALL_HOUR = "o:hour"
ALL_TOMORROW = "o:tomorrow"
WEEKDAY_PICK = "q:day"
WEEKDAY_NEW = "q:new"


def _button(text: str, action: str, record_id: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=f"{action}:{record_id}")


def reminder(record_id: int) -> InlineKeyboardMarkup:
    """Напоминание в момент срока."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("сделал", DONE, record_id), _button("не напоминать", STOP, record_id)],
            [
                _button("через час", HOUR, record_id),
                _button("завтра", TOMORROW, record_id),
                _button("через неделю", WEEK, record_id),
            ],
        ]
    )


def overdue_single(record_id: int) -> InlineKeyboardMarkup:
    """Одна просроченная позиция."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("сделал", DONE, record_id),
                _button("через час", HOUR, record_id),
                _button("завтра", TOMORROW, record_id),
                _button("через неделю", WEEK, record_id),
            ]
        ]
    )


def overdue_list(items: list[tuple[int, str]], limit: int = 10) -> InlineKeyboardMarkup:
    """Список просроченного: по кнопке на позицию плюс две общие.

    Предел тот же, что и у текста списка: кнопка без строки и строка без
    кнопки одинаково сбивают с толку.
    """
    rows = [[_button(f"{title} сделал", DONE, record_id)] for record_id, title in items[:limit]]
    rows.append(
        [
            InlineKeyboardButton(text="всё через час", callback_data=f"{ALL_HOUR}:0"),
            InlineKeyboardButton(text="всё завтра", callback_data=f"{ALL_TOMORROW}:0"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def when_done(record_id: int) -> InlineKeyboardMarkup:
    """Просрочено больше суток — «сделал» раскрывается."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("сегодня", DONE_TODAY, record_id),
                _button("вчера", DONE_YESTERDAY, record_id),
                _button("в срок", DONE_ONTIME, record_id),
            ]
        ]
    )


def weekday_choice(question_id: int, options: list[str]) -> InlineKeyboardMarkup:
    """Уточнение: вариантов не больше трёх, плюс «это новое»."""
    row = [
        InlineKeyboardButton(text=label, callback_data=f"{WEEKDAY_PICK}:{question_id}:{index}")
        for index, label in enumerate(options[:2])
    ]
    row.append(InlineKeyboardButton(text="это новое", callback_data=f"{WEEKDAY_NEW}:{question_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])
