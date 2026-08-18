"""Индексация Markdown-документации: скан → секции → локальные эмбеддинги → JSON."""

from __future__ import annotations

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


def build_index(config: dict[str, Any], client: OllamaClient) -> dict[str, Any]:
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

    vectors: list[list[float]] = []
    batch_size = 16
    inputs = [embedding_input(section) for section in sections]
    for start in range(0, len(inputs), batch_size):
        vectors.extend(client.embed(model, inputs[start : start + batch_size]))

    index = {
        "version": 1,
        "docs_dir": str(docs_dir),
        "embedding_model": model,
        "documents": documents,
        "sections": [
            {**asdict(section), "embedding": vector}
            for section, vector in zip(sections, vectors)
        ],
    }
    save_index(config, index)
    return index


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
        "embedding_model": index.get("embedding_model", ""),
        "documents": index.get("documents", []),
        "documents_count": len(index.get("documents", [])),
        "sections_count": len(index.get("sections", [])),
    }
