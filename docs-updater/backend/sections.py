"""Разбор документа на разделы с точными границами: чтобы править один раздел, а не весь текст."""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class SectionSpan:
    index: int
    level: int
    title: str
    path: str  # «Раздел > Подраздел»
    start: int  # номер первой строки раздела (с 0), включая сам заголовок
    end: int  # номер строки после последней строки раздела


def outline(content: str) -> list[SectionSpan]:
    """Список разделов документа. Заголовки внутри блоков кода не считаются заголовками."""
    lines = (content or "").replace("\r\n", "\n").split("\n")
    found: list[tuple[int, int, str]] = []  # (номер строки, уровень, заголовок)
    in_fence = False
    for number, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match:
            found.append((number, len(match.group(1)), match.group(2).strip()))

    spans: list[SectionSpan] = []
    stack: list[str] = []
    for position, (number, level, title) in enumerate(found):
        # Раздел заканчивается там, где начинается следующий заголовок того же или более высокого уровня.
        end = len(lines)
        for next_number, next_level, _ in found[position + 1 :]:
            if next_level <= level:
                end = next_number
                break
        stack = stack[: level - 1]
        while len(stack) < level - 1:
            stack.append("")
        stack.append(title)
        spans.append(
            SectionSpan(
                index=position,
                level=level,
                title=title,
                path=" > ".join(part for part in stack if part),
                start=number,
                end=end,
            )
        )
    return spans


def section_text(content: str, span: SectionSpan) -> str:
    lines = (content or "").replace("\r\n", "\n").split("\n")
    return "\n".join(lines[span.start : span.end]).strip("\n")


def replace_section(content: str, span: SectionSpan, replacement: str) -> str:
    """Вклеивает обновлённый раздел обратно в документ, не трогая остальной текст."""
    normalized = (content or "").replace("\r\n", "\n")
    lines = normalized.split("\n")
    new_lines = replacement.replace("\r\n", "\n").strip("\n").split("\n")

    # Сохраняем пустые строки, которыми раздел отделялся от следующего.
    original = lines[span.start : span.end]
    trailing = 0
    while trailing < len(original) and original[len(original) - 1 - trailing].strip() == "":
        trailing += 1
    if trailing == 0 and span.end < len(lines):
        trailing = 1
    return "\n".join(lines[: span.start] + new_lines + [""] * trailing + lines[span.end :])


def document_map(content: str) -> str:
    """Оглавление документа — контекст для модели, когда правим один раздел."""
    return "\n".join(f"{'  ' * (span.level - 1)}- {span.title}" for span in outline(content))
