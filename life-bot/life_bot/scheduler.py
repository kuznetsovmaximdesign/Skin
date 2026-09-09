"""Планировщик. APScheduler, хранилище задач — в той же SQLite.

Источник правды — база, а не список задач: раз в минуту планировщик спрашивает
у неё, кому пора напомнить. Поэтому перезапуск ничего не теряет, а пропущенное
за время простоя уходит первым же тиком.

Задачи ссылаются на функции по имени модуля, а не на связанные методы: только
такие ссылки переживают запись в хранилище.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .dates import now_local
from .quiet import parse_slots
from .reminders import Reminders

log = logging.getLogger(__name__)

TICK_SECONDS = 60


@dataclass
class Runtime:
    reminders: Reminders
    tz: str

    def now(self) -> datetime:
        return now_local(self.tz)


_runtime: Runtime | None = None


def set_runtime(runtime: Runtime | None) -> None:
    global _runtime
    _runtime = runtime


async def tick_job() -> None:
    """Раз в минуту: кому пора напомнить."""
    if _runtime is None:
        return
    try:
        await _runtime.reminders.send_due(_runtime.now())
    except Exception:
        log.exception("тик планировщика упал")


async def overdue_job() -> None:
    """Слот просрочки: всё несделанное одним сообщением."""
    if _runtime is None:
        return
    try:
        await _runtime.reminders.send_overdue(_runtime.now())
    except Exception:
        log.exception("слот просрочки упал")


class Scheduler:
    def __init__(self, reminders: Reminders, db_path: Path | str, tz: str = "Europe/Moscow") -> None:
        self.reminders = reminders
        self.db_path = Path(db_path)
        self.tz = tz
        self._scheduler = None

    def start(self) -> None:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        set_runtime(Runtime(reminders=self.reminders, tz=self.tz))
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{self.db_path}")},
            timezone=self.tz,
            job_defaults={"coalesce": True, "misfire_grace_time": 3600},
        )
        self._scheduler.add_job(
            "life_bot.scheduler:tick_job",
            trigger="interval",
            seconds=TICK_SECONDS,
            id="tick",
            replace_existing=True,
        )
        slots = parse_slots(self.reminders.setting("overdue_slots", "09:00,19:00"))
        for slot in slots:
            self._scheduler.add_job(
                "life_bot.scheduler:overdue_job",
                trigger="cron",
                hour=slot.hour,
                minute=slot.minute,
                id=f"overdue_{slot.hour:02d}{slot.minute:02d}",
                replace_existing=True,
            )
        # Чистка только после запуска: до него задачи из хранилища не видны.
        self._scheduler.start()
        self._drop_stale_slots(slots)
        log.info("планировщик запущен, слоты просрочки: %s", [str(s) for s in slots])

    def _drop_stale_slots(self, slots) -> None:
        """Слоты изменились в настройках — старые задачи из хранилища убираем."""
        wanted = {f"overdue_{slot.hour:02d}{slot.minute:02d}" for slot in slots}
        for job in self._scheduler.get_jobs():
            if job.id.startswith("overdue_") and job.id not in wanted:
                job.remove()

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        set_runtime(None)
