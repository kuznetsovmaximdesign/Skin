"""Каркас бота: приём входящих, сроки, напоминания."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from .config import Config, ConfigError
from .db import Database
from .deadlines import Deadlines
from .heartbeat import Heartbeat
from .intake import Intake
from .logging_setup import setup as setup_logging
from .questions import Questions
from .reminders import Reminders
from .router import Handlers, build_router
from .scheduler import Scheduler
from .voice import Transcriber

log = logging.getLogger(__name__)


def build(config: Config, bot: Bot, db: Database) -> tuple[Handlers, Scheduler]:
    """Собирает части воедино. Вынесено из run, чтобы проверялось без polling."""
    tz = str((db.get_profile(1) or {})["tz"] or "Europe/Moscow")
    deadlines = Deadlines(db, tz=tz)
    questions = Questions(db, tz=tz)
    reminders = Reminders(
        bot=bot, db=db, deadlines=deadlines, chat_id=config.owner_id, tz=tz
    )
    transcriber = Transcriber(
        enabled=config.voice.enabled,
        model=config.voice.model,
        device=config.voice.device,
        compute_type=config.voice.compute_type,
    )
    handlers = Handlers(
        db=db,
        intake=Intake(db=db, files_dir=config.files_dir, transcriber=transcriber),
        deadlines=deadlines,
        questions=questions,
        reminders=reminders,
        tz=tz,
    )
    return handlers, Scheduler(reminders, config.db_path, tz=tz)


async def run(config: Config) -> None:
    db = Database(config.db_path)
    db.connect()
    db.bind_tg_user(config.owner_id)
    log.info("база %s, записей в inbox_raw: %s", config.db_path, db.count_raw())

    heartbeat = Heartbeat(config.heartbeat.url, config.heartbeat.interval_seconds)
    bot = Bot(token=config.token, default=DefaultBotProperties())
    handlers, scheduler = build(config, bot, db)

    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(handlers, config.owner_id))

    try:
        me = await bot.get_me()
        log.info("бот @%s запущен", me.username)
        scheduler.start()
        heartbeat.start()
        await handlers.reminders.update_counter(handlers.now())
        await dispatcher.start_polling(bot, handle_signals=True)
    finally:
        scheduler.shutdown()
        await heartbeat.stop()
        await bot.session.close()
        db.close()
        log.info("остановлен")


def main() -> int:
    try:
        config = Config.load()
    except ConfigError as exc:
        print(f"конфигурация: {exc}", file=sys.stderr)
        print("скопируй config.example.toml в config.toml и поставь права 600", file=sys.stderr)
        return 1
    setup_logging(config.log_path, config.log_level)
    asyncio.run(run(config))
    return 0
