"""Определение типа статьи и проверка по схеме своего типа.

Типы и их схемы приходят из docs-config/article-type-schemas.json: обязательные секции,
их порядок, ожидаемые уровни заголовков и обязательные метаполя (свои для каждого профиля).

Тип берётся из front-matter (`type_id`), иначе определяется эвристикой по структуре.
"""

from __future__ import annotations

import re
from typing import Any

from .. import docs_config
from . import profiles as profile_rules

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TYPE_KEYS = ("type_id", "article_type", "type", "тип")


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


def title_of(text: str) -> str:
    for _, level, title in outline(text):
        if level == 1:
            return title
    meta = profile_rules.front_matter(text)
    return str(meta.get("title", ""))


def declared_type(text: str) -> str:
    meta = profile_rules.front_matter(text)
    for key in TYPE_KEYS:
        value = meta.get(key)
        if value:
            return str(value).strip()
    return ""


def score_type(entry: dict[str, Any], text: str, headings: list[str], title: str) -> int:
    """Насколько документ похож на этот тип: совпадения заголовков, начала названия, слов."""
    detect = entry.get("detect") or {}
    score = 0

    for heading in detect.get("headings_any", []):
        if any(heading.lower() == item.lower() for item in headings):
            score += 3
    for prefix in detect.get("title_prefix", []):
        if title.lower().startswith(str(prefix).lower()):
            score += 2
    lowered = (text or "").lower()
    for needle in detect.get("text_contains", []):
        if str(needle).lower() in lowered:
            score += 1

    # Обязательные секции типа, найденные в документе, тоже говорят в его пользу.
    required = entry.get("required_sections") or []
    if required:
        matched = sum(1 for item in required if any(item.lower() == h.lower() for h in headings))
        if matched == len(required):
            score += 2
        elif matched:
            score += 1
    return score


def detect_type(config: dict[str, Any], text: str, profile: str = "") -> dict[str, Any]:
    """Тип статьи: из front-matter или эвристикой по структуре."""
    available = docs_config.types(config)
    if not available:
        return {"type_id": "", "source": "типы не заданы", "confidence": 0, "known": False}

    declared = declared_type(text)
    if declared:
        known = any(entry["type_id"] == declared for entry in available)
        return {"type_id": declared, "source": "front-matter", "confidence": 10, "known": known}

    headings = [title for _, _, title in outline(text)]
    title = title_of(text)
    candidates = [
        entry for entry in available
        if not profile or not entry["profiles"] or profile in entry["profiles"]
    ] or available

    def best_of(entries: list[dict[str, Any]]) -> tuple[int, dict[str, Any] | None]:
        scored = sorted(
            ((score_type(entry, text, headings, title), entry) for entry in entries),
            key=lambda item: item[0],
            reverse=True,
        )
        return scored[0] if scored else (0, None)

    best_score, best = best_of(candidates)
    source = "эвристика по структуре"

    if best_score <= 0 and len(candidates) != len(available):
        # Профиль мог определиться неточно — не даём ему скрыть очевидный тип.
        best_score, best = best_of(available)
        source = "эвристика по структуре (вне типов профиля)"

    if best_score <= 0 or best is None:
        return {"type_id": "", "source": "эвристика: не опознан", "confidence": 0, "known": False}
    return {
        "type_id": best["type_id"],
        "source": source,
        "confidence": best_score,
        "known": True,
    }


def check(text: str, config: dict[str, Any], profile: str, type_id: str) -> list[Any]:
    """Проверка документа по схеме своего типа: секции, порядок, уровни, метаполя."""
    from . import Violation

    entry = docs_config.type_by_id(config, type_id)
    if not entry:
        return []

    violations: list[Violation] = []

    # Тип может быть неприменим к профилю: это разные поколения шаблона.
    if entry["profiles"] and profile and profile not in entry["profiles"]:
        violations.append(
            Violation(
                "schema", "type-profile-mismatch", "warning", 0,
                f"Тип «{entry['name']}» не используется в профиле «{profile}»",
                type_id, kind="recommendation",
            )
        )

    headings = outline(text)
    titles = [title for _, _, title in headings]

    required = entry["required_sections"]
    for name in required:
        if not any(name.lower() == title.lower() for title in titles):
            violations.append(
                Violation("schema", "missing-section", "error", 0,
                          f"Тип «{entry['name']}»: нет обязательного раздела «{name}»", name)
            )

    if entry["enforce_order"] and required:
        present = [name for name in required if any(name.lower() == t.lower() for t in titles)]
        actual = [t for t in titles if any(t.lower() == name.lower() for name in present)]
        if [item.lower() for item in actual] != [item.lower() for item in present]:
            violations.append(
                Violation("schema", "section-order", "error", 0,
                          "Порядок разделов не по шаблону типа: ожидается " + " → ".join(present),
                          " → ".join(actual))
            )

    for line_number, level, title in headings:
        expected = entry["section_levels"].get(title)
        if expected and expected != level:
            violations.append(
                Violation("schema", "section-level", "error", line_number,
                          f"Раздел «{title}» должен быть уровня {expected}, а не {level}", title)
            )

    # Метаполя: свой набор для каждого профиля шаблона.
    fields = docs_config.required_meta_for(entry, profile)
    if fields:
        meta = profile_rules.meta_fields(text)
        for field in fields:
            if not str(meta.get(field, "")).strip():
                violations.append(
                    Violation("schema", "missing-meta", "error", 1,
                              f"Профиль «{profile}»: не заполнено метаполе «{field}»", field)
                )
    return violations
