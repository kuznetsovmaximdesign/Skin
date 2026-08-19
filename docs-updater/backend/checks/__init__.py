"""Единый модуль проверки соответствия: формулировка + оформление + структура.

Проверки детерминированные и офлайновые. Внешние линтеры (Vale, markdownlint-cli2)
используются, если установлены; встроенные правила работают всегда, поэтому сервис
не зависит от наличия бинарников.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..config import resolve_path
from . import article_types, external, kdoc as kdoc_rules
from . import markdown as markdown_rules, profiles as profile_rules
from . import prose as prose_rules, schema as schema_rules


@dataclass
class Violation:
    source: str  # prose | markdown | schema | kdoc | vale | markdownlint
    rule: str
    severity: str  # error | warning
    line: int
    message: str
    excerpt: str = ""
    # «нарушение» — обязательное правило, «рекомендация» — спорное или необязательное
    kind: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "violation" if self.severity == "error" else "recommendation"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe_document(text: str, config: dict[str, Any]) -> dict[str, Any]:
    """Профиль шаблона и тип статьи: от них зависит, какие правила применять."""
    from .. import docs_config

    known_profiles = docs_config.profiles(config)
    profile = profile_rules.detect_profile(text, known_profiles)
    detected = article_types.detect_type(config, text, profile["profile"])
    entry = docs_config.type_by_id(config, detected["type_id"]) if detected["type_id"] else None
    return {
        "profile": profile["profile"],
        "profile_source": profile["source"],
        "type_id": detected["type_id"],
        "type_name": (entry or {}).get("name", ""),
        "type_source": detected["source"],
        "lintable": (entry or {}).get("lintable", True),
        "type_note": (entry or {}).get("note", ""),
        "market_specific": (entry or {}).get("market_specific", False),
    }


def checks_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("checks", {}) or {}


# Правила, которые применимы только к документу целиком, а не к отдельному разделу.
DOCUMENT_ONLY_RULES = {"first-heading-h1", "single-h1"}


def run_checks(
    text: str,
    config: dict[str, Any],
    only_lines: tuple[int, int] | None = None,
    scope: str = "document",
) -> list[Violation]:
    """Прогоняет все включённые проверки и возвращает единый список нарушений.

    scope="section" проверяет фрагмент документа: правила про «один заголовок первого
    уровня» и шаблон целого документа при этом не применяются.
    only_lines ограничивает результат диапазоном строк — так проверяются только
    изменённые секции, а не весь документ.
    """
    settings = checks_config(config)
    if not settings.get("enabled", True):
        return []

    document = describe_document(text, config)

    # Нелинтуемые типы: детальный API вынесен во внешний инструмент.
    if scope == "document" and not document["lintable"]:
        note = document["type_note"] or "Тип статьи вне области текстовой проверки."
        return [
            Violation(
                "schema", "not-lintable", "warning", 0,
                f"«{document['type_name']}»: {note}", document["type_id"], kind="recommendation",
            )
        ]

    violations: list[Violation] = []
    if settings.get("builtin_prose", True):
        violations += prose_rules.check(text, settings, config)
    if settings.get("builtin_markdown", True):
        violations += markdown_rules.check(text, settings)

    if settings.get("schema", True) and scope == "document":
        if document["type_id"]:
            # Тип известен — проверяем по его собственной схеме.
            violations += article_types.check(text, config, document["profile"], document["type_id"])
        else:
            violations += schema_rules.check(text, settings, config)

    if settings.get("kdoc", True) is not False:
        violations += kdoc_rules.check(text, config, document["profile"], document["type_id"], scope)

    if scope == "section":
        violations = [item for item in violations if item.rule not in DOCUMENT_ONLY_RULES]

    violations += external.run_vale(text, settings, config)
    violations += external.run_markdownlint(text, settings, config)

    if only_lines:
        start, end = only_lines
        violations = [item for item in violations if start <= item.line <= end or item.line == 0]

    violations.sort(key=lambda item: (item.line, item.source, item.rule))
    return violations


def summarize(violations: list[Violation]) -> dict[str, Any]:
    errors = [item for item in violations if item.severity == "error"]
    return {
        "total": len(violations),
        "errors": len(errors),
        "warnings": len(violations) - len(errors),
        "violations": sum(1 for item in violations if item.kind == "violation"),
        "recommendations": sum(1 for item in violations if item.kind == "recommendation"),
        "by_source": {
            source: sum(1 for item in violations if item.source == source)
            for source in sorted({item.source for item in violations})
        },
    }


def as_instruction(violations: list[Violation], limit: int = 20) -> str:
    """Список нарушений в виде, который понятен модели при починке."""
    lines = []
    for item in violations[:limit]:
        place = f"строка {item.line}: " if item.line else ""
        excerpt = f" (в тексте: «{item.excerpt}»)" if item.excerpt else ""
        lines.append(f"- {place}{item.message}{excerpt} [{item.source}/{item.rule}]")
    return "\n".join(lines)


def resolve(config: dict[str, Any], key: str, default: str) -> "object":
    return resolve_path(checks_config(config).get(key, default))
