"""Отправка напоминаний и закреплённый счётчик.

Три правила жизненного цикла сообщений из docs/life_bot_replies.md:
напоминание в момент срока приходит новым сообщением — это событие;
список просроченного и счётчик редактируются на месте, дубли не плодятся.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import keyboards, texts
from .db import Database
from .deadlines import Deadline, Deadlines
from .quiet import in_quiet, shift_out_of_quiet

log = logging.getLogger(__name__)

COUNTER_KEY = "counter_message_id"
OVERDUE_KEY = "overdue_message_id"
OVERDUE_TEXT_KEY = "overdue_message_text"


class Reminders:
    def __init__(
        self,
        *,
        bot,
        db: Database,
        deadlines: Deadlines,
        chat_id: int,
        tz: str = "Europe/Moscow",
        profile_id: int = 1,
    ) -> None:
        self.bot = bot
        self.db = db
        self.deadlines = deadlines
        self.chat_id = chat_id
        self.tz = tz
        self.profile_id = profile_id

    # -- настройки ------------------------------------------------------

    def setting(self, key: str, default: str = "") -> str:
        return self.db.get_setting(key, self.profile_id) or default

    def _remember(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings (profile_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(profile_id, key) DO UPDATE SET value = excluded.value",
            (self.profile_id, key, value),
        )

    def quiet_bounds(self) -> tuple[str, str]:
        return self.setting("quiet_from", "00:00"), self.setting("quiet_to", "09:00")

    def is_quiet(self, now: datetime) -> bool:
        return in_quiet(now, *self.quiet_bounds())

    def out_of_quiet(self, moment: datetime) -> datetime:
        return shift_out_of_quiet(moment, *self.quiet_bounds())

    # -- напоминания ----------------------------------------------------

    async def send_due(self, now: datetime) -> list[int]:
        """Наступившие сроки. Каждый — отдельным новым сообщением."""
        if self.is_quiet(now):
            return []
        sent: list[int] = []
        for deadline in self.deadlines.not_yet_sent(now):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=texts.reminder(deadline.title),
                    reply_markup=keyboards.reminder(deadline.record_id),
                )
            except Exception:
                log.exception("напоминание %s не ушло", deadline.record_id)
                continue
            self.deadlines.mark_sent(deadline.record_id)
            sent.append(deadline.record_id)
        if sent:
            await self.update_counter(now)
        return sent

    async def send_overdue(self, now: datetime) -> bool:
        """Всё просроченное — одним сообщением, а не по одному.

        Сообщение редактируется на месте: за неделю молчания в чате не должно
        появиться четырнадцать одинаковых списков.
        """
        if self.is_quiet(now):
            return False
        overdue = self.deadlines.overdue(now)
        if not overdue:
            return False

        if len(overdue) == 1:
            deadline = overdue[0]
            days = deadline.days_overdue(now)
            # Срок наступил сегодня — это ещё не «третий день», а тот же текст.
            text = (
                texts.reminder(deadline.title)
                if days == 0
                else texts.reminder_overdue(deadline.title, days, deadline.sent_count + 1)
            )
            markup = keyboards.overdue_single(deadline.record_id)
        else:
            text = texts.overdue_list([(d.title, d.days_overdue(now)) for d in overdue])
            markup = keyboards.overdue_list([(d.record_id, d.title) for d in overdue])

        if text == self.setting(OVERDUE_TEXT_KEY) and self.setting(OVERDUE_KEY):
            return False                                   # ничего не изменилось

        await self._send_or_edit(OVERDUE_KEY, text, markup)
        self._remember(OVERDUE_TEXT_KEY, text)
        for deadline in overdue:
            self.deadlines.mark_sent(deadline.record_id)
        await self.update_counter(now)
        return True

    async def _send_or_edit(self, key: str, text: str, markup) -> int | None:
        message_id = self.setting(key)
        if message_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id, message_id=int(message_id), text=text, reply_markup=markup
                )
                return int(message_id)
            except Exception:
                log.info("сообщение %s не переписалось, отправляю заново", message_id)
        try:
            message = await self.bot.send_message(chat_id=self.chat_id, text=text, reply_markup=markup)
        except Exception:
            log.exception("сообщение не отправлено")
            return None
        self._remember(key, str(message.message_id))
        return message.message_id

    # -- счётчик --------------------------------------------------------

    def inbox_count(self) -> int:
        rows = self.db.execute(
            "SELECT COUNT(*) AS n FROM inbox_raw WHERE parse_state IN ('new', 'unparsed')"
        )
        return int(rows[0]["n"])

    async def update_counter(self, now: datetime) -> str:
        """Закреплённое сообщение редактируется, а не отправляется заново.

        Тихих часов не касается: правка закреплённого не шлёт уведомление.
        """
        overdue, today = self.deadlines.counts(now)
        text = texts.counter(overdue, today, self.inbox_count())

        message_id = self.setting(COUNTER_KEY)
        if message_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id, message_id=int(message_id), text=text
                )
                return text
            except Exception:
                log.info("счётчик %s не переписался, создаю новый", message_id)

        try:
            message = await self.bot.send_message(chat_id=self.chat_id, text=text)
            self._remember(COUNTER_KEY, str(message.message_id))
            await self.bot.pin_chat_message(
                chat_id=self.chat_id, message_id=message.message_id, disable_notification=True
            )
        except Exception:
            log.exception("счётчик не создан")
        return text

    # -- действия по кнопкам --------------------------------------------

    def snooze_until(self, deadline: Deadline, action: str, now: datetime) -> datetime:
        if action == keyboards.HOUR:
            target = now + timedelta(hours=1)
        elif action == keyboards.TOMORROW:
            target = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            target = (now + timedelta(days=7)).replace(hour=9, minute=0, second=0, microsecond=0)
        return self.out_of_quiet(target)
