"""Каркас: чужие сообщения до приёма не доходят."""


from aiogram import Bot, Dispatcher

from life_bot.bot import build_router
from life_bot.db import Database
from life_bot.intake import Intake


class RecordingIntake(Intake):
    def __init__(self, db, files_dir):
        super().__init__(db, files_dir)
        self.seen = []

    async def accept(self, message, bot):
        self.seen.append(message.message_id)
        return len(self.seen)


async def test_only_owner_reaches_intake(db: Database, tmp_path):
    import datetime as dt

    from aiogram.types import Chat, Message, Update, User

    intake = RecordingIntake(db, tmp_path)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(intake, owner_id=555))
    bot = Bot(token="42:TEST")

    def update(user_id, message_id):
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

    await dispatcher.feed_update(bot, update(555, 1))
    await dispatcher.feed_update(bot, update(999, 2))
    await bot.session.close()

    assert intake.seen == [1]
