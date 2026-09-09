"""Помощник для скриптов бэкапа: снимок, целостность, счёт строк."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from life_bot.db import Database

spec = importlib.util.spec_from_file_location(
    "dbtool", Path(__file__).resolve().parent.parent / "deploy" / "dbtool.py"
)
dbtool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dbtool)


def test_snapshot_copies_everything(db: Database, tmp_path, capsys):
    db.save_raw(kind="text", tg_message_id=1, text="раз")
    db.save_raw(kind="voice", tg_message_id=2)

    copy = tmp_path / "snapshot.db"
    assert dbtool.snapshot(str(db.path), str(copy)) == 0

    dbtool.count(str(copy), "inbox_raw")
    assert capsys.readouterr().out.strip() == "2"

    dbtool.tables(str(copy))
    assert int(capsys.readouterr().out.strip()) == 21


def test_snapshot_does_not_touch_the_source(db: Database, tmp_path):
    db.save_raw(kind="text", tg_message_id=1, text="раз")
    dbtool.snapshot(str(db.path), str(tmp_path / "snapshot.db"))
    assert db.count_raw() == 1  # исходная база открывается только на чтение


def test_check_says_ok(db: Database, capsys):
    assert dbtool.check(str(db.path)) == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_check_fails_on_a_broken_file(tmp_path, capsys):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises(sqlite3.DatabaseError):
        dbtool.check(str(broken))


def test_main_rejects_unknown_command(capsys):
    assert dbtool.main(["dbtool.py", "чепуха"]) == 2
    assert "использование" in capsys.readouterr().err


def test_main_reports_missing_database(capsys):
    assert dbtool.main(["dbtool.py", "check", "/нет/такого/файла.db"]) == 1
    assert "sqlite" in capsys.readouterr().err
