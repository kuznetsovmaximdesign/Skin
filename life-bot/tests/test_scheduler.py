"""Планировщик: задачи в той же базе, слоты просрочки из настроек."""

from datetime import datetime, timedelta

from life_bot import scheduler as scheduler_module
from life_bot.db import Database
from life_bot.deadlines import Deadlines
from life_bot.reminders import Reminders
from life_bot.scheduler import Runtime, Scheduler, overdue_job, tick_job
from tests.fakes import FakeBot

NOW = datetime(2026, 9, 9, 15, 0)


def build(db: Database):
    bot = FakeBot()
    deadlines = Deadlines(db, tz="Europe/Moscow")
    return bot, deadlines, Reminders(bot=bot, db=db, deadlines=deadlines, chat_id=100, tz="Europe/Moscow")


async def test_jobs_are_registered_from_settings(db: Database):
    _, _, reminders = build(db)
    scheduler = Scheduler(reminders, db.path, tz="Europe/Moscow")
    scheduler.start()
    try:
        ids = {job.id for job in scheduler._scheduler.get_jobs()}
        assert ids == {"tick", "overdue_0900", "overdue_1900"}
    finally:
        scheduler.shutdown()


async def test_job_store_lives_in_the_same_database(db: Database):
    _, _, reminders = build(db)
    scheduler = Scheduler(reminders, db.path, tz="Europe/Moscow")
    scheduler.start()
    try:
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "apscheduler_jobs" in tables
    finally:
        scheduler.shutdown()


async def test_changed_slots_replace_the_old_ones(db: Database):
    _, _, reminders = build(db)
    Scheduler(reminders, db.path, tz="Europe/Moscow").start()
    scheduler_module.set_runtime(None)

    db.execute("UPDATE settings SET value = '08:00' WHERE key = 'overdue_slots'")
    scheduler = Scheduler(reminders, db.path, tz="Europe/Moscow")
    scheduler.start()
    try:
        ids = {job.id for job in scheduler._scheduler.get_jobs()}
        assert ids == {"tick", "overdue_0800"}
    finally:
        scheduler.shutdown()


async def test_tick_sends_what_is_due(db: Database):
    bot, deadlines, reminders = build(db)
    deadlines.create(title="ОСАГО", due_at=NOW - timedelta(minutes=1))
    scheduler_module.set_runtime(Runtime(reminders=reminders, tz="Europe/Moscow"))
    try:
        object.__setattr__(scheduler_module._runtime, "now", lambda: NOW)
        await tick_job()
        assert bot.texts[0] == "ОСАГО."
    finally:
        scheduler_module.set_runtime(None)


async def test_slot_sends_the_overdue_list(db: Database):
    bot, deadlines, reminders = build(db)
    for i in range(2):
        record_id = deadlines.create(title=f"дело {i}", due_at=NOW - timedelta(days=2))
        deadlines.mark_sent(record_id)
    scheduler_module.set_runtime(Runtime(reminders=reminders, tz="Europe/Moscow"))
    try:
        object.__setattr__(scheduler_module._runtime, "now", lambda: NOW)
        await overdue_job()
        assert bot.texts[0].startswith("Просрочено:")
    finally:
        scheduler_module.set_runtime(None)


async def test_jobs_without_a_runtime_do_nothing():
    scheduler_module.set_runtime(None)
    await tick_job()
    await overdue_job()
