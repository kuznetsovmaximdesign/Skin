"""Каркас бота. Этап 1: приём текста, голоса и фото в inbox_raw."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message

from .config import Config, ConfigError
from .db import Database
from .intake import Intake
from .logging_setup import setup as setup_logging
from .voice import Transcriber

log = logging.getLogger(__name__)


def build_router(intake: Intake, owner_id: int) -> Router:
    router = Router(name="intake")
    router.message.filter(F.from_user.id == owner_id)

    @router.message()
    async def on_message(message: Message, bot: Bot) -> None:
        try:
            await intake.accept(message, bot)
        except Exception:
            # Сюда попадать не должны: accept пишет в базу до всех рискованных
            # операций. Но если попали — в лог, пользователю ничего.
            log.exception("сообщение %s не принято", message.message_id)

    return router


async def run(config: Config) -> None:
    db = Database(config.db_path)
    db.connect()
    db.bind_tg_user(config.owner_id)
    log.info("база %s, записей в inbox_raw: %s", config.db_path, db.count_raw())

    transcriber = Transcriber(
        enabled=config.voice.enabled,
        model=config.voice.model,
        device=config.voice.device,
        compute_type=config.voice.compute_type,
    )
    intake = Intake(db=db, files_dir=config.files_dir, transcriber=transcriber)

    bot = Bot(token=config.token, default=DefaultBotProperties())
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(intake, config.owner_id))

    try:
        me = await bot.get_me()
        log.info("бот @%s запущен", me.username)
        await dispatcher.start_polling(bot, handle_signals=True)
    finally:
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
