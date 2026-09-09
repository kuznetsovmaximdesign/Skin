"""Каркас: чужие сообщения и чужие кнопки до обработчиков не доходят."""

import datetime as dt

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from life_bot.router import build_router


class RecordingHandlers:
    def __init__(self):
        self.messages = []
        self.callbacks = []

    async def on_message(self, message, bot):
        self.messages.append(message.message_id)

    async def on_callback(self, callback):
        self.callbacks.append(callback.data)


def update_with_message(user_id, message_id):
    return Update(
        update_id=message_id,
        message=Message(
            message_id=message_id,
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=100, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="кто-то"),
            text="привет",
        ),
    )


def update_with_callback(user_id, update_id):
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=User(id=user_id, is_bot=False, first_name="кто-то"),
            chat_instance="1",
            data="d:done:1",
        ),
    )


async def test_only_owner_reaches_the_handlers():
    handlers = RecordingHandlers()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(handlers, owner_id=555))
    bot = Bot(token="42:TEST")

    await dispatcher.feed_update(bot, update_with_message(555, 1))
    await dispatcher.feed_update(bot, update_with_message(999, 2))
    await dispatcher.feed_update(bot, update_with_callback(555, 3))
    await dispatcher.feed_update(bot, update_with_callback(999, 4))
    await bot.session.close()

    assert handlers.messages == [1]
    assert handlers.callbacks == ["d:done:1"]


async def test_a_broken_handler_does_not_crash_the_bot():
    class Boom(RecordingHandlers):
        async def on_message(self, message, bot):
            raise RuntimeError("сломалось")

    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(Boom(), owner_id=555))
    bot = Bot(token="42:TEST")
    await dispatcher.feed_update(bot, update_with_message(555, 1))   # исключение съедено
    await bot.session.close()
