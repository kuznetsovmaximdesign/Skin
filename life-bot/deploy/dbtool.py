#!/usr/bin/env python3
"""Работа с базой для скриптов бэкапа.

Отдельным файлом, чтобы не тащить в зависимости консольный sqlite3: python3
на машине с ботом есть всегда, sqlite3 — не обязательно.
"""

import sqlite3
import sys


def snapshot(src: str, dst: str) -> int:
    """Согласованный снимок. Копировать файл нельзя: база в режиме WAL."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(dst)
    with target:
        source.backup(target)
    source.close()
    target.close()
    return 0


def check(db: str) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    print(result)
    return 0 if result == "ok" else 1


def count(db: str, table: str) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    print(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    conn.close()
    return 0


def tables(db: str) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    print(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
    conn.close()
    return 0


COMMANDS = {"snapshot": snapshot, "check": check, "count": count, "tables": tables}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(f"использование: {argv[0]} {{{'|'.join(COMMANDS)}}} ...", file=sys.stderr)
        return 2
    try:
        return COMMANDS[argv[1]](*argv[2:])
    except TypeError:
        print("неверное число аргументов", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"sqlite: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
