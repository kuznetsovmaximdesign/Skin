"""Индексация Markdown-документации: скан → секции → локальные эмбеддинги → JSON."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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
    """Строит индекс. Секции, которые не изменились с прошлого раза, не пересчитываются."""
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    model = config["ollama"]["embedding_model"]
    max_chars = int(config["search"]["chunk_max_chars"])

    client.ensure_model(model)

    files = find_markdown_files(docs_dir)
    sections: list[Section] = []
    documents: list[dict[str, Any]] = []
    for path in files:
        content = read_text(path)
        rel = path.relative_to(docs_dir).as_posix()
        title = document_title(content, path)
        file_sections = split_sections(content, rel, title, max_chars)
        sections.extend(file_sections)
        documents.append(
            {
                "path": rel,
                "title": title,
                "chars": len(content),
                "sections": len(file_sections),
                "modified": path.stat().st_mtime,
            }
        )

    inputs = [embedding_input(section) for section in sections]
    hashes = [section_hash(text) for text in inputs]

    known = reusable_embeddings(config, model, str(docs_dir))
    missing = [text for text, digest in zip(inputs, hashes) if digest not in known]
    fresh: dict[str, list[float]] = {}
    batch_size = 16
    for start in range(0, len(missing), batch_size):
        batch = missing[start : start + batch_size]
        for text, vector in zip(batch, client.embed(model, batch)):
            fresh[section_hash(text)] = vector

    vectors = [known.get(digest) or fresh.get(digest, []) for digest in hashes]

    index = {
        "version": 2,
        "docs_dir": str(docs_dir),
        "embedding_model": model,
        "documents": documents,
        "reused_sections": len(sections) - len(missing),
        "computed_sections": len(missing),
        "sections": [
            {**asdict(section), "hash": digest, "embedding": vector}
            for section, digest, vector in zip(sections, hashes, vectors)
        ],
    }
    save_index(config, index)
    return index


def reusable_embeddings(config: dict[str, Any], model: str, docs_dir: str) -> dict[str, list[float]]:
    """Эмбеддинги из прошлого индекса — годятся, только если та же модель и та же папка."""
    previous = load_index(config)
    if not previous or previous.get("embedding_model") != model or previous.get("docs_dir") != docs_dir:
        return {}
    return {
        section["hash"]: section["embedding"]
        for section in previous.get("sections", [])
        if section.get("hash") and section.get("embedding")
    }


def index_path(config: dict[str, Any]) -> Path:
    return resolve_path(config["paths"]["index_file"])


def save_index(config: dict[str, Any], index: dict[str, Any]) -> None:
    path = index_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def load_index(config: dict[str, Any]) -> dict[str, Any] | None:
    path = index_path(config)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def index_summary(index: dict[str, Any] | None) -> dict[str, Any]:
    if not index:
        return {"exists": False, "documents": [], "documents_count": 0, "sections_count": 0}
    return {
        "exists": True,
        "docs_dir": index.get("docs_dir", ""),
        "reused_sections": index.get("reused_sections", 0),
        "computed_sections": index.get("computed_sections", len(index.get("sections", []))),
        "embedding_model": index.get("embedding_model", ""),
        "documents": index.get("documents", []),
        "documents_count": len(index.get("documents", [])),
        "sections_count": len(index.get("sections", [])),
    }
