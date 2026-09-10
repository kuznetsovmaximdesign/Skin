"""Схема применяется как есть, входящее пишется до любого разбора."""

import sqlite3

import pytest

from life_bot.db import Database, utc_now_iso

EXPECTED_TABLES = {
    "inbox_raw", "records", "deadlines", "meals", "metrics", "wishes", "people",
    "gifts", "places", "parse_patterns", "llm_calls", "pending_questions", "links",
    "categories", "profiles", "settings", "record_edits", "notes", "shopping_items",
    "watchlist", "findings",
}


def test_schema_creates_every_table(db: Database):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    assert EXPECTED_TABLES <= names


def test_wal_and_foreign_keys(db: Database):
    assert db.execute("PRAGMA journal_mode")[0][0].lower() == "wal"
    assert db.execute("PRAGMA foreign_keys")[0][0] == 1


def test_seed_data(db: Database):
    profile = db.get_profile(1)
    assert profile["name"] == "Максим"
    assert profile["tz"] == "Europe/Moscow"
    assert db.get_setting("overdue_slots") == "09:00,19:00"
    assert db.get_setting("confidence_min") == "0.8"
    assert len(db.all_settings()) == 14
    codes = {r["code"] for r in db.execute("SELECT code FROM categories")}
    assert codes == {"home", "health", "car", "docs", "personal"}


def test_save_raw_defaults(db: Database):
    raw_id = db.save_raw(kind="text", tg_message_id=11, text="напомни про ОСАГО")
    row = db.get_raw(raw_id)
    assert row["kind"] == "text"
    assert row["text"] == "напомни про ОСАГО"
    assert row["parse_state"] == "new"  # разбора на этапе 1 нет
    assert row["parser"] is None
    assert row["transcript"] is None
    assert row["file_path"] is None
    assert row["created_at"].endswith("+00:00")


@pytest.mark.parametrize("kind", ["text", "voice", "photo", "forward"])
def test_all_kinds_accepted(db: Database, kind: str):
    raw_id = db.save_raw(kind=kind, tg_message_id=hash(kind) % 10_000)
    assert db.get_raw(raw_id)["kind"] == kind


def test_unknown_kind_rejected(db: Database):
    with pytest.raises(ValueError):
        db.save_raw(kind="video", tg_message_id=1)


def test_transcript_file_and_error_updates(db: Database):
    raw_id = db.save_raw(kind="voice", tg_message_id=12)
    db.set_file_path(raw_id, "/var/files/12.ogg")
    db.set_transcript(raw_id, "купить молоко")
    db.set_error(raw_id, "whisper: боом")
    row = db.get_raw(raw_id)
    assert row["file_path"] == "/var/files/12.ogg"
    assert row["transcript"] == "купить молоко"
    assert row["error"].startswith("whisper:")


def test_raw_survives_restart(tmp_path):
    path = tmp_path / "restart.db"
    first = Database(path)
    first.connect()
    raw_id = first.save_raw(kind="text", tg_message_id=99, text="жив")
    first.close()

    second = Database(path)
    second.connect()  # схема уже есть, повторно не применяется
    assert second.get_raw(raw_id)["text"] == "жив"
    assert second.count_raw() == 1
    second.close()


def test_bind_tg_user_is_written_once(db: Database):
    db.bind_tg_user(555)
    db.bind_tg_user(777)
    assert db.get_profile(1)["tg_user_id"] == 555


def test_records_require_existing_profile(db: Database):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO records (created_at, profile_id, type) VALUES (?, ?, ?)",
            (utc_now_iso(), 42, "note"),
        )
