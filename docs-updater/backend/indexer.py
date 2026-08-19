"""Индексация Markdown-документации: скан → секции → локальные эмбеддинги → JSON."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import index_store
from .config import resolve_path
from .ollama_client import OllamaClient

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Section:
    doc_path: str  # путь относительно папки документации
    doc_title: str
    heading: str  # «Раздел > Подраздел»
    text: str
    start_line: int


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def find_markdown_files(docs_dir: Path) -> list[Path]:
    if not docs_dir.exists():
        return []
    files = [
        path
        for path in sorted(docs_dir.rglob("*.md"))
        if path.is_file() and not any(part.startswith(".") for part in path.parts)
    ]
    return files


def document_title(content: str, path: Path) -> str:
    for line in content.splitlines():
        match = HEADING_RE.match(line)
        if match:
            return match.group(2).strip()
    return path.stem


def split_sections(content: str, doc_path: str, doc_title: str, max_chars: int) -> list[Section]:
    """Режет документ по заголовкам; слишком длинные секции делит на части по абзацам."""
    lines = content.splitlines()
    stack: list[str] = []
    buffer: list[str] = []
    current_heading = doc_title
    start_line = 1
    raw: list[Section] = []

    def flush(end_heading: str, line_no: int) -> None:
        text = "\n".join(buffer).strip()
        if text:
            raw.append(Section(doc_path, doc_title, end_heading, text, line_no))

    in_fence = False
    for index, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            flush(current_heading, start_line)
            level = len(match.group(1))
            title = match.group(2).strip()
            stack = stack[: level - 1]
            while len(stack) < level - 1:
                stack.append("")
            stack.append(title)
            current_heading = " > ".join(part for part in stack if part)
            buffer = [line]
            start_line = index
        else:
            buffer.append(line)
    flush(current_heading, start_line)

    sections: list[Section] = []
    for section in raw:
        if len(section.text) <= max_chars:
            sections.append(section)
            continue
        chunk: list[str] = []
        size = 0
        for paragraph in section.text.split("\n\n"):
            if size + len(paragraph) > max_chars and chunk:
                sections.append(
                    Section(section.doc_path, section.doc_title, section.heading, "\n\n".join(chunk), section.start_line)
                )
                chunk, size = [], 0
            chunk.append(paragraph)
            size += len(paragraph) + 2
        if chunk:
            sections.append(
                Section(section.doc_path, section.doc_title, section.heading, "\n\n".join(chunk), section.start_line)
            )
    return sections


def embedding_input(section: Section) -> str:
    """Текст, который уходит в модель эмбеддингов: заголовки дают контекст."""
    return f"Документ: {section.doc_title}\nРаздел: {section.heading}\n\n{section.text}"


def section_hash(text: str) -> str:
    """Отпечаток секции: по нему переиспользуем ранее посчитанные эмбеддинги."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def build_index(config: dict[str, Any], client: OllamaClient) -> dict[str, Any]:
    """Строит индекс по одному файлу за раз.

    Вся документация в память не загружается: файл читается, режется на секции,
    эмбеддинги считаются небольшими батчами и сразу пишутся в SQLite.
    Секции, которые не изменились с прошлого раза, не пересчитываются.
    """
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    model = config["ollama"]["embedding_model"]
    max_chars = int(config["search"]["chunk_max_chars"])
    batch_size = max(1, int(config["search"].get("embed_batch", 8)))

    client.ensure_model(model)

    files = find_markdown_files(docs_dir)
    reused = 0
    computed = 0

    with index_store.connect(index_path(config)) as connection:
        # Эмбеддинги из прошлого индекса годятся, только если та же модель и та же папка.
        can_reuse = (
            index_store.get_meta(connection, "embedding_model") == model
            and index_store.get_meta(connection, "docs_dir") == str(docs_dir)
        )
        index_store.prepare_rebuild(connection)

        for path in files:
            content = read_text(path)
            rel = path.relative_to(docs_dir).as_posix()
            title = document_title(content, path)
            file_sections = split_sections(content, rel, title, max_chars)

            for start in range(0, len(file_sections), batch_size):
                batch = file_sections[start : start + batch_size]
                inputs = [embedding_input(section) for section in batch]
                digests = [section_hash(text) for text in inputs]

                vectors: list[list[float] | None] = []
                pending: list[str] = []
                for text, digest in zip(inputs, digests):
                    known = index_store.find_embedding(connection, digest) if can_reuse else None
                    vectors.append(known)
                    if known is None:
                        pending.append(text)

                fresh = client.embed(model, pending) if pending else []
                fresh_iter = iter(fresh)
                rows = []
                for section, digest, vector in zip(batch, digests, vectors):
                    if vector is None:
                        vector = next(fresh_iter, [])
                        computed += 1
                    else:
                        reused += 1
                    rows.append(
                        (
                            section.doc_path,
                            section.doc_title,
                            section.heading,
                            section.text,
                            section.start_line,
                            digest,
                            index_store.pack(vector),
                        )
                    )
                index_store.add_sections(connection, rows)

            content_hash = section_hash(content)
            document = {
                "path": rel,
                "title": title,
                "chars": len(content),
                "sections": len(file_sections),
                "modified": path.stat().st_mtime,
                "content_hash": content_hash,
            }
            # Резюме «что документирует» пересчитывается только при изменении документа.
            carried = index_store.previous_summary(connection, rel, content_hash) if can_reuse else None
            if carried:
                document.update(carried)
            index_store.add_document(connection, document)
            del content, file_sections

        index_store.finish_rebuild(connection)
        index_store.set_meta(connection, "version", 3)
        index_store.set_meta(connection, "docs_dir", str(docs_dir))
        index_store.set_meta(connection, "embedding_model", model)
        index_store.set_meta(connection, "reused_sections", reused)
        index_store.set_meta(connection, "computed_sections", computed)

    return index_summary(config)


def index_path(config: dict[str, Any]) -> Path:
    return resolve_path(config["paths"]["index_file"])


def index_exists(config: dict[str, Any]) -> bool:
    return index_store.exists(index_path(config))


def index_summary(config: dict[str, Any]) -> dict[str, Any]:
    """Короткая сводка об индексе для интерфейса."""
    path = index_path(config)
    if not index_store.exists(path):
        return {"exists": False, "documents": [], "documents_count": 0, "sections_count": 0}
    with index_store.connect(path) as connection:
        documents_count, sections_count = index_store.counts(connection)
        return {
            "exists": True,
            "docs_dir": index_store.get_meta(connection, "docs_dir"),
            "embedding_model": index_store.get_meta(connection, "embedding_model"),
            "reused_sections": int(index_store.get_meta(connection, "reused_sections", "0")),
            "computed_sections": int(index_store.get_meta(connection, "computed_sections", "0")),
            "documents": index_store.documents(connection),
            "documents_count": documents_count,
            "sections_count": sections_count,
        }
