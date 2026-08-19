"""Проверка документа по шаблону продукта: обязательные разделы, порядок, front-matter.

Шаблон описан отдельным YAML — его правит редактор, а не программист.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from ..config import resolve_path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
ADMONITION_RE = re.compile(r"^>\s*\[!(\w+)\]")

_cache: dict[str, Any] = {}


def load_schema(config: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(settings.get("template_schema", "data/template.schema.yaml"))
    if not path.exists():
        return {}
    key = f"{path}:{path.stat().st_mtime}"
    if key not in _cache:
        _cache.clear()
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _cache[key] = loaded if isinstance(loaded, dict) else {}
    return _cache[key]


def outline(text: str) -> list[tuple[int, int, str]]:
    """(строка, уровень, заголовок) — заголовки вне блоков кода."""
    result = []
    in_fence = False
    for number, line in enumerate((text or "").replace("\r\n", "\n").split("\n"), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match:
            result.append((number, len(match.group(1)), match.group(2).strip()))
    return result


def check(text: str, settings: dict[str, Any], config: dict[str, Any]) -> list[Any]:
    from . import Violation

    template = load_schema(config, settings)
    if not template:
        return []

    violations: list[Violation] = []
    headings = outline(text)
    titles = [title for _, _, title in headings]

    required = template.get("required_sections") or []
    for title in required:
        if title not in titles:
            violations.append(
                Violation("schema", "missing-section", "error", 0, f"Нет обязательного раздела «{title}»", title)
            )

    if template.get("enforce_order", True):
        present = [title for title in required if title in titles]
        actual = [title for title in titles if title in present]
        if actual != present:
            violations.append(
                Violation(
                    "schema", "section-order", "error", 0,
                    "Порядок разделов не по шаблону: ожидается " + " → ".join(present),
                    " → ".join(actual),
                )
            )

    levels = template.get("section_levels") or {}
    for line_number, level, title in headings:
        expected = levels.get(title)
        if expected and expected != level:
            violations.append(
                Violation("schema", "section-level", "error", line_number,
                          f"Раздел «{title}» должен быть уровня {expected}, а не {level}", title)
            )

    fields = template.get("front_matter") or []
    if fields:
        match = FRONT_MATTER_RE.match((text or "").replace("\r\n", "\n"))
        if not match:
            violations.append(
                Violation("schema", "front-matter", "error", 1,
                          "Нет блока front-matter с полями: " + ", ".join(fields), "")
            )
        else:
            data = yaml.safe_load(match.group(1)) or {}
            for field in fields:
                if field not in data or data.get(field) in (None, ""):
                    violations.append(
                        Violation("schema", "front-matter-field", "error", 1,
                                  f"В front-matter не заполнено поле «{field}»", field)
                    )

    if template.get("require_image_alt", True):
        for number, line in enumerate((text or "").split("\n"), start=1):
            for alt, src in IMAGE_RE.findall(line):
                if not alt.strip():
                    violations.append(
                        Violation("schema", "image-alt", "error", number,
                                  f"У картинки {src} нет альтернативного текста", src)
                    )

    allowed = template.get("admonitions")
    if allowed:
        for number, line in enumerate((text or "").split("\n"), start=1):
            found = ADMONITION_RE.match(line.strip())
            if found and found.group(1).upper() not in {item.upper() for item in allowed}:
                violations.append(
                    Violation("schema", "admonition-type", "error", number,
                              f"Врезка «{found.group(1)}» не из списка: {', '.join(allowed)}", found.group(1))
                )
    return violations
