"""Локальное хранилище индекса: SQLite-файл рядом с сервисом.

Эмбеддинги лежат бинарно (float32), строки читаются курсором по одной — вся
документация никогда не оказывается в памяти целиком.
"""

from __future__ import annotations

import sqlite3
from array import array
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS documents (
    path TEXT PRIMARY KEY, title TEXT, chars INTEGER, sections INTEGER, modified REAL,
    content_hash TEXT, summary TEXT, entities TEXT, summary_embedding BLOB
);
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_path TEXT NOT NULL,
    doc_title TEXT,
    heading TEXT,
    text TEXT,
    start_line INTEGER,
    hash TEXT,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS sections_hash_idx ON sections(hash);
CREATE INDEX IF NOT EXISTS sections_doc_idx ON sections(doc_path);
"""


def pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    vector = array("f")
    vector.frombytes(blob)
    return vector.tolist()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def exists(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with connect(path) as connection:
            row = connection.execute("SELECT COUNT(*) FROM sections").fetchone()
        return bool(row and row[0])
    except sqlite3.DatabaseError:
        return False


def get_meta(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def find_embedding(connection: sqlite3.Connection, digest: str) -> list[float] | None:
    """Ищет ранее посчитанный эмбеддинг по отпечатку секции (переиспользование при переиндексации)."""
    row = connection.execute(
        "SELECT embedding FROM sections WHERE hash = ? LIMIT 1", (digest,)
    ).fetchone()
    return unpack(row[0]) if row and row[0] else None


def prepare_rebuild(connection: sqlite3.Connection) -> None:
    """Готовит временные таблицы: старый индекс ещё нужен, чтобы брать из него эмбеддинги."""
    connection.executescript(
        """
        DROP TABLE IF EXISTS sections_new;
        DROP TABLE IF EXISTS documents_new;
        CREATE TABLE sections_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_path TEXT NOT NULL, doc_title TEXT, heading TEXT, text TEXT,
            start_line INTEGER, hash TEXT, embedding BLOB
        );
        CREATE TABLE documents_new (
            path TEXT PRIMARY KEY, title TEXT, chars INTEGER, sections INTEGER, modified REAL,
            content_hash TEXT, summary TEXT, entities TEXT, summary_embedding BLOB
        );
        """
    )


def add_document(connection: sqlite3.Connection, document: dict[str, Any]) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO documents_new"
        "(path, title, chars, sections, modified, content_hash, summary, entities, summary_embedding)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (
            document["path"],
            document["title"],
            document["chars"],
            document["sections"],
            document["modified"],
            document.get("content_hash", ""),
            document.get("summary", ""),
            document.get("entities", ""),
            document.get("summary_embedding"),
        ),
    )


def previous_summary(connection: sqlite3.Connection, path: str, content_hash: str) -> dict[str, Any] | None:
    """Резюме документа из прошлого индекса — если содержимое не менялось, считать заново не нужно."""
    row = connection.execute(
        "SELECT summary, entities, summary_embedding FROM documents WHERE path = ? AND content_hash = ?",
        (path, content_hash),
    ).fetchone()
    if not row or not row[0]:
        return None
    return {"summary": row[0], "entities": row[1] or "", "summary_embedding": row[2]}


def documents_without_summary(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT path FROM documents WHERE summary IS NULL OR summary = '' ORDER BY path"
    ).fetchall()
    return [row[0] for row in rows]


def set_summary(
    connection: sqlite3.Connection, path: str, summary: str, entities: str, embedding: bytes | None
) -> None:
    connection.execute(
        "UPDATE documents SET summary = ?, entities = ?, summary_embedding = ? WHERE path = ?",
        (summary, entities, embedding, path),
    )


def iter_summaries(connection: sqlite3.Connection):
    """Курсор по резюме документов: путь, заголовок, резюме, сущности, вектор."""
    cursor = connection.execute(
        "SELECT path, title, summary, entities, summary_embedding FROM documents"
        " WHERE summary IS NOT NULL AND summary != ''"
    )
    for row in cursor:
        yield row[0], row[1], row[2], row[3], (unpack(row[4]) if row[4] else [])


def add_sections(connection: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    connection.executemany(
        "INSERT INTO sections_new(doc_path, doc_title, heading, text, start_line, hash, embedding)"
        " VALUES(?,?,?,?,?,?,?)",
        rows,
    )


def finish_rebuild(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE sections;
        DROP TABLE documents;
        ALTER TABLE sections_new RENAME TO sections;
        ALTER TABLE documents_new RENAME TO documents;
        CREATE INDEX IF NOT EXISTS sections_hash_idx ON sections(hash);
        CREATE INDEX IF NOT EXISTS sections_doc_idx ON sections(doc_path);
        """
    )


def iter_embeddings(connection: sqlite3.Connection) -> Iterator[tuple[int, str, str, str, list[float]]]:
    """Курсор по секциям: id, документ, заголовок документа, заголовок раздела, вектор.

    Тексты секций специально не читаем — они нужны только для нескольких победителей.
    """
    cursor = connection.execute(
        "SELECT id, doc_path, doc_title, heading, embedding FROM sections WHERE embedding IS NOT NULL"
    )
    for row in cursor:
        yield row[0], row[1], row[2], row[3], unpack(row[4])


def section_text(connection: sqlite3.Connection, section_id: int) -> str:
    row = connection.execute("SELECT text FROM sections WHERE id = ?", (section_id,)).fetchone()
    return row[0] if row else ""


def documents(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT path, title, chars, sections, modified, summary, entities FROM documents ORDER BY path"
    ).fetchall()
    return [
        {
            "path": row[0],
            "title": row[1],
            "chars": row[2],
            "sections": row[3],
            "modified": row[4],
            "summary": row[5] or "",
            "entities": row[6] or "",
        }
        for row in rows
    ]


def counts(connection: sqlite3.Connection) -> tuple[int, int]:
    documents_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    sections_count = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    return documents_count, sections_count
