"""Проверка оформления Markdown: заголовки, списки, код, таблицы, строки.

Встроенный аналог markdownlint — работает без Node.js. Если в системе есть
markdownlint-cli2, его результаты добавляются сверху (см. external.py).
"""

from __future__ import annotations

import re
from typing import Any

HEADING_RE = re.compile(r"^(#{1,6})(\s*)(.*)$")
BULLET_RE = re.compile(r"^(\s*)([-*+])\s+\S")
ORDERED_RE = re.compile(r"^(\s*)(\d+)([.)])\s+\S")


def check(text: str, settings: dict[str, Any]) -> list[Any]:
    from . import Violation

    violations: list[Violation] = []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    max_length = int(settings.get("max_line_length", 120))
    want_bullet = settings.get("bullet_marker", "-")
    require_fence_language = bool(settings.get("require_fence_language", True))

    in_fence = False
    fence_start = 0
    previous_level = 0
    first_heading_seen = False
    top_level_count = 0
    blank_run = 0

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()

        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = number
                if require_fence_language and stripped == "```":
                    violations.append(
                        Violation("markdown", "fenced-code-language", "warning", number,
                                  "У блока кода не указан язык", "```")
                    )
            else:
                in_fence = False
            continue
        if in_fence:
            continue

        if not stripped:
            blank_run += 1
            if blank_run > 1:
                violations.append(
                    Violation("markdown", "multiple-blanks", "warning", number,
                              "Подряд больше одной пустой строки", "")
                )
            continue
        blank_run = 0

        if line.rstrip() != line:
            violations.append(
                Violation("markdown", "trailing-spaces", "warning", number, "Пробелы в конце строки", "")
            )

        if len(line) > max_length:
            violations.append(
                Violation("markdown", "line-length", "warning", number,
                          f"Строка длиннее {max_length} символов ({len(line)})", line[:40] + "…")
            )

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(3).strip()
            if heading.group(2) != " ":
                violations.append(
                    Violation("markdown", "heading-space", "error", number,
                              "После # должен быть ровно один пробел", line[:40])
                )
            if not title:
                violations.append(
                    Violation("markdown", "heading-empty", "error", number, "Пустой заголовок", "")
                )
            if title.endswith((".", ",", ";", ":")):
                violations.append(
                    Violation("markdown", "heading-punctuation", "warning", number,
                              "Заголовок не должен заканчиваться знаком препинания", title)
                )
            if level == 1:
                top_level_count += 1
                if top_level_count > 1:
                    violations.append(
                        Violation("markdown", "single-h1", "error", number,
                                  "В документе должен быть только один заголовок первого уровня", title)
                    )
            if not first_heading_seen:
                first_heading_seen = True
                if level != 1:
                    violations.append(
                        Violation("markdown", "first-heading-h1", "error", number,
                                  "Документ должен начинаться с заголовка первого уровня", title)
                    )
            elif level > previous_level + 1:
                violations.append(
                    Violation("markdown", "heading-increment", "error", number,
                              f"Уровень заголовка перескочил с {previous_level} на {level}", title)
                )
            previous_level = level
            continue

        bullet = BULLET_RE.match(line)
        if bullet and bullet.group(2) != want_bullet:
            violations.append(
                Violation("markdown", "bullet-marker", "warning", number,
                          f"Маркер списка «{bullet.group(2)}», по правилам — «{want_bullet}»", line[:30])
            )

    if in_fence:
        violations.append(
            Violation("markdown", "fenced-code-unclosed", "error", fence_start, "Блок кода не закрыт", "```")
        )
    if not first_heading_seen and (text or "").strip():
        violations.append(
            Violation("markdown", "first-heading-h1", "error", 1, "В документе нет ни одного заголовка", "")
        )
    return violations
