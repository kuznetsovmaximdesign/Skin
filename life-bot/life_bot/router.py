"""Обработчики: входящее сообщение в срок и действия по кнопкам.

Слои разбора на этом этапе два: висящий вопрос и правила. Модели подключаются
этапом позже. Фраза без даты остаётся в инбоксе и ждёт своего слоя.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from . import keyboards, texts
from .dates import now_local, parse_when
from .db import Database
from .deadlines import Deadlines
from .intake import Intake
from .questions import Questions
from .reminders import Reminders

log = logging.getLogger(__name__)


class Handlers:
    """Собран отдельно от роутера, чтобы каждый шаг проверялся без Telegram."""

    def __init__(
        self,
        *,
        db: Database,
        intake: Intake,
        deadlines: Deadlines,
        questions: Questions,
        reminders: Reminders,
        tz: str = "Europe/Moscow",
        clock=None,
    ) -> None:
        self.db = db
        self.intake = intake
        self.deadlines = deadlines
        self.questions = questions
        self.reminders = reminders
        self.tz = tz
        self._clock = clock            # подменяется в тестах, в бою — системные часы

    def now(self) -> datetime:
        return self._clock() if self._clock else now_local(self.tz)

    # -- входящее -------------------------------------------------------

    def text_of(self, raw_id: int) -> str:
        row = self.db.get_raw(raw_id)
        if row is None:
            return ""
        return (row["text"] or row["transcript"] or "").strip()

    async def on_message(self, message: Message, bot: Bot) -> None:
        raw_id = await self.intake.accept(message, bot)
        if raw_id is None:
            return

        now = self.now()
        self.questions.expire(now)
        text = self.text_of(raw_id)
        if not text:
            await self.reminders.update_counter(now)
            return

        when = parse_when(text, now)
        if when is None:
            # Дат нет — своего слоя эта фраза ещё не дождалась, лежит в инбоксе.
            await self.reminders.update_counter(now)
            return

        if when.ambiguous and when.alternatives:
            await self._ask_which_day(message, raw_id, when, now)
            return

        record_id = self.deadlines.create_from_when(when, raw_id=raw_id)
        self.db.set_parsed(
            raw_id,
            parser="rules",
            parse_json=json.dumps(
                {"type": "deadline", "due_at": when.due_at.isoformat(), "title": when.title},
                ensure_ascii=False,
            ),
            confidence=1.0,
        )
        deadline = self.deadlines.get(record_id)
        await message.reply(
            texts.confirm_deadline(
                title=deadline.title,
                due_at=deadline.due_at,
                remind_at=deadline.remind_at,
                today=now.date(),
                repeat_rule=deadline.repeat_rule,
            )
        )
        await self.reminders.update_counter(now)

    async def _ask_which_day(self, message: Message, raw_id: int, when, now: datetime) -> None:
        """Пятница неоднозначна — спрашиваем, а не угадываем."""
        from .dates import format_date_full

        options = [day.isoformat() for day in when.alternatives]
        question = texts.weekday_question(list(when.alternatives), now.date())
        question_id = self.questions.ask(
            raw_id=raw_id, field="due_at", question=question, options=options, now=now
        )
        labels = [format_date_full(day, today=now.date()) for day in when.alternatives]
        self.db.execute(
            "UPDATE inbox_raw SET parse_json = ? WHERE id = ?",
            (json.dumps({"pending": when.title, "hour": when.due_at.hour}, ensure_ascii=False), raw_id),
        )
        await message.reply(question, reply_markup=keyboards.weekday_choice(question_id, labels))

    # -- кнопки ---------------------------------------------------------

    async def on_callback(self, callback: CallbackQuery) -> None:
        data = callback.data or ""
        parts = data.split(":")
        if len(parts) < 3:
            await callback.answer()
            return
        prefix, action, tail = parts[0], f"{parts[0]}:{parts[1]}", parts[2:]
        now = self.now()

        if prefix == "q":
            await self._answer_question(callback, action, tail, now)
        elif prefix == "o":
            await self._snooze_all(callback, action, now)
        else:
            await self._one_deadline(callback, action, int(tail[0]), now)
        await self.reminders.update_counter(now)

    async def _one_deadline(self, callback: CallbackQuery, action: str, record_id: int, now: datetime) -> None:
        deadline = self.deadlines.get(record_id)
        if deadline is None:
            await callback.answer()
            return

        if deadline.state != "active":
            # Повторное нажатие той же кнопки второго действия не создаёт.
            await self._rewrite(callback, texts.closed(deadline.title))
            await callback.answer()
            return

        if action == keyboards.DONE:
            if deadline.days_overdue(now) >= 1:
                await self._rewrite(
                    callback, texts.WHEN_DONE, keyboards.when_done(record_id)
                )
                await callback.answer()
                return
            await self._close(callback, record_id, now, now)
            return

        if action in (keyboards.DONE_TODAY, keyboards.DONE_YESTERDAY, keyboards.DONE_ONTIME):
            done_at = {
                keyboards.DONE_TODAY: now,
                keyboards.DONE_YESTERDAY: (now - timedelta(days=1)).replace(hour=12, minute=0),
                keyboards.DONE_ONTIME: deadline.due_at,
            }[action]
            await self._close(callback, record_id, done_at, now)
            return

        if action == keyboards.STOP:
            self.deadlines.stop(record_id)
            await self._rewrite(callback, texts.stopped(deadline.title))
            await callback.answer()
            return

        if action in (keyboards.HOUR, keyboards.TOMORROW, keyboards.WEEK):
            until = self.reminders.snooze_until(deadline, action, now)
            self.deadlines.snooze(record_id, until)
            await self._rewrite(callback, texts.snoozed(deadline.title, until, now.date()))
            await callback.answer()
            return

        await callback.answer()

    async def _close(self, callback: CallbackQuery, record_id: int, done_at: datetime, now: datetime) -> None:
        deadline = self.deadlines.get(record_id)
        next_id = self.deadlines.close(record_id, done_at=done_at)
        if next_id is None:
            await self._rewrite(callback, texts.closed(deadline.title))
        else:
            nxt = self.deadlines.get(next_id)
            await self._rewrite(callback, texts.closed(deadline.title, nxt.due_at, now.date()))
        await callback.answer()

    async def _snooze_all(self, callback: CallbackQuery, action: str, now: datetime) -> None:
        overdue = self.deadlines.overdue(now)
        if not overdue:
            await callback.answer()
            return
        until = self.reminders.snooze_until(
            overdue[0], keyboards.HOUR if action == keyboards.ALL_HOUR else keyboards.TOMORROW, now
        )
        for deadline in overdue:
            self.deadlines.snooze(deadline.record_id, until)
        await self._rewrite(callback, texts.moved_to(until, now.date()))
        await callback.answer()

    async def _answer_question(self, callback: CallbackQuery, action: str, tail: list[str], now: datetime) -> None:
        question_id = int(tail[0])
        row = self.questions.get(question_id)
        if row is None or row["state"] != "open":
            await callback.answer()
            return

        if action == keyboards.WEEKDAY_NEW:
            self.questions.close(question_id, state="answered")
            await self._rewrite(callback, texts.NOT_UNDERSTOOD)
            await callback.answer()
            return

        from datetime import date as date_type

        options = self.questions.options(question_id)
        index = int(tail[1]) if len(tail) > 1 else 0
        chosen = date_type.fromisoformat(options[index])
        raw_id = int(row["raw_id"])
        stored = self.db.get_raw(raw_id)
        payload = json.loads(stored["parse_json"] or "{}") if stored else {}
        title = payload.get("pending") or "без названия"
        hour = int(payload.get("hour", 9))

        due_at = datetime(chosen.year, chosen.month, chosen.day, hour, 0)
        record_id = self.deadlines.create(title=title, due_at=due_at, raw_id=raw_id)
        self.db.set_parsed(raw_id, parser="rules", confidence=1.0)
        self.questions.close(question_id, state="answered")

        deadline = self.deadlines.get(record_id)
        await self._rewrite(
            callback,
            texts.confirm_deadline(
                title=deadline.title,
                due_at=deadline.due_at,
                remind_at=deadline.remind_at,
                today=now.date(),
            ),
        )
        await callback.answer()

    async def _rewrite(self, callback: CallbackQuery, text: str, markup=None) -> None:
        """Сообщение переписывается в результат, мёртвых кнопок не остаётся."""
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            log.info("сообщение не переписалось: %s", text)


def build_router(handlers: Handlers, owner_id: int) -> Router:
    router = Router(name="life")
    router.message.filter(F.from_user.id == owner_id)
    router.callback_query.filter(F.from_user.id == owner_id)

    @router.callback_query()
    async def on_callback(callback: CallbackQuery) -> None:
        try:
            await handlers.on_callback(callback)
        except Exception:
            log.exception("кнопка %s не отработала", callback.data)
            await callback.answer()

    @router.message()
    async def on_message(message: Message, bot: Bot) -> None:
        try:
            await handlers.on_message(message, bot)
        except Exception:
            log.exception("сообщение %s не обработано", message.message_id)

    return router
