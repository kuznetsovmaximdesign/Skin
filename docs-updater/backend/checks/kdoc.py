"""Кастомные правила KDOC-*: отдельный проход по структуре документа.

Это не стандартные коды markdownlint, а собственные проверки. Каждое правило включается
и отключается, привязано к типу статьи и/или профилю шаблона, а его уровень задаётся в
docs-config/markdownlint-rule-candidates.md и может быть переопределён в config.yaml.

Спорные правила (открытые вопросы разбора) по умолчанию идут как рекомендации.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .. import docs_config
from . import profiles as profile_rules

ADMONITION_MARKER_RE = re.compile(r">\s*\[!(\w+)\]|:::\s*(\w+)|\{\.?(?:admonition|callout)\s+type=[\"'](\w+)[\"']\}")
ADMONITION_ANY_RE = re.compile(r"^\s*(>|:::|<div)", re.IGNORECASE)
COLOR_HINT_RE = re.compile(
    r"(class=[\"'][^\"']*(yellow|red|green|blue|orange|жёлт|красн|зелён|син)[^\"']*[\"'])"
    r"|(?:^|\s)(жёлтая|красная|зелёная|синяя)\s+(?:врезка|плашка|рамка)",
    re.IGNORECASE,
)
ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+\S")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
PARALLEL_ITEM_RE = re.compile(r"^\s*[-*+]\s+([^—:]{2,60})\s*[—:]\s+\S")
UI_QUOTED_RE = re.compile(r"(нажмите|выберите|откройте|перейдите в|включите)\s+[«\"']([^»\"']{2,40})[»\"']", re.IGNORECASE)
BOLD_RE = re.compile(r"\*\*[^*]+\*\*")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
# Аббревиатура — только буквы: KB-1001 и подобные идентификаторы не считаются.
ABBR_RE = re.compile(r"(?<![\w/-])([A-ZА-Я]{2,6})(?![\w/-])")
EXPANSION_RE = re.compile(r"\(([^)]{4,})\)")
RESULT_RE = re.compile(r"^\s*(в результате|результат:|после этого)", re.IGNORECASE)
LEADIN_RE = re.compile(r"^\s*чтобы\s+.+:\s*$", re.IGNORECASE)
LOG_FENCE_RE = re.compile(r"^```\s*(log|logs|output|console|text)?\s*$", re.IGNORECASE)

MIN_PARALLEL_ITEMS = 3


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Строки прозы: без блоков кода и без front-matter.

    Вывод логов внутри блоков кода не проверяется ни на язык, ни на стиль.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if closing:
            start = closing + 1

    result: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if number <= start:
            continue
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        result.append((number, line))
    return result


# --- отдельные правила ------------------------------------------------------


def rule_admonition_type(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Тип врезки задаётся явным маркером, а не цветом или оформлением."""
    allowed = {item.lower() for item in context["admonition_types"]}
    found: list[tuple[int, str, str]] = []

    for number, line in prose_lines(text):
        color = COLOR_HINT_RE.search(line)
        if color:
            found.append((number, "Тип врезки нельзя выводить из цвета — нужен явный атрибут типа", color.group(0)[:40]))
            continue

        marker = ADMONITION_MARKER_RE.search(line)
        if marker:
            kind = next(group for group in marker.groups() if group)
            if kind.lower() not in allowed:
                found.append(
                    (number, f"Тип врезки «{kind}» не из списка: {', '.join(sorted(allowed))}", kind)
                )
            continue

    # Врезка — это блок цитаты целиком: тип должен быть в его первой строке,
    # продолжение блока проверять не нужно.
    inside_quote = False
    for number, line in prose_lines(text):
        is_quote = line.lstrip().startswith(">")
        if not is_quote:
            inside_quote = False
            continue
        if inside_quote:
            continue
        inside_quote = True
        stripped = line.lstrip("> ").strip()
        if stripped and not ADMONITION_MARKER_RE.search(line):
            found.append((number, "У врезки нет машиночитаемого типа (например, > [!NOTE])", stripped[:40]))
    return found


def rule_leadin(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Перед нумерованными шагами нужен лид-ин вида «Чтобы …:»."""
    lines = prose_lines(text)
    found = []
    for index, (number, line) in enumerate(lines):
        if not ORDERED_RE.match(line):
            continue
        if index and ORDERED_RE.match(lines[index - 1][1]):
            continue  # не начало списка
        previous = ""
        for back in range(index - 1, max(-1, index - 4), -1):
            if lines[back][1].strip():
                previous = lines[back][1].strip()
                break
        if not LEADIN_RE.match(previous):
            found.append((number, "Перед шагами нет лид-ина вида «Чтобы …:»", previous[:60] or "(пусто)"))
    return found


def rule_result(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """После шагов нужен абзац-результат."""
    lines = prose_lines(text)
    last_step = None
    for index, (number, line) in enumerate(lines):
        if ORDERED_RE.match(line):
            last_step = index
    if last_step is None:
        return []
    for _, line in lines[last_step + 1 :]:
        if RESULT_RE.match(line.strip()):
            return []
    return [(lines[last_step][0], "После шагов нет абзаца с результатом («В результате …»)", "")]


def rule_ui_bold(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Названия элементов интерфейса — полужирным, а не в кавычках."""
    found = []
    for number, line in prose_lines(text):
        for match in UI_QUOTED_RE.finditer(line):
            label = match.group(2)
            if f"**{label}**" not in line:
                found.append((number, f"Название элемента интерфейса «{label}» должно быть полужирным", label))
    return found


def rule_table_for_parallel(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Три и более однотипных пункта «Название — описание» лучше показать таблицей."""
    found = []
    streak: list[tuple[int, str]] = []
    for number, line in prose_lines(text):
        if PARALLEL_ITEM_RE.match(line):
            streak.append((number, line))
            continue
        if line.strip() == "":
            continue
        if len(streak) >= MIN_PARALLEL_ITEMS:
            found.append((streak[0][0], f"Подряд {len(streak)} однотипных пункта — уместнее таблица", ""))
        streak = []
    if len(streak) >= MIN_PARALLEL_ITEMS:
        found.append((streak[0][0], f"Подряд {len(streak)} однотипных пункта — уместнее таблица", ""))
    return found


def rule_footer_meta(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """В конце статьи должен быть блок метаданных: идентификатор и дата обновления."""
    meta = profile_rules.meta_fields(text)
    tail = "\n".join((text or "").splitlines()[-12:])
    has_footer = bool(profile_rules.FOOTER_META_RE.search(tail))
    if has_footer or (meta.get("article_id") and meta.get("updated")):
        return []
    return [(0, "Нет блока метаданных в конце статьи (идентификатор, дата обновления)", "")]


def rule_abbr_expansion(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Аббревиатура расшифровывается при первом употреблении, кроме имён из глоссария."""
    known = {item.upper() for item in context["glossary"].get("keep", [])}
    known |= {item.upper() for item in context["glossary"].get("accepted", [])}
    seen: set[str] = set()
    found = []
    for number, raw_line in prose_lines(text):
        # Маркеры врезок и ссылки — не аббревиатуры.
        line = ADMONITION_MARKER_RE.sub(" ", raw_line)
        line = re.sub(r"\[!\w+\]", " ", line)
        for match in ABBR_RE.finditer(line):
            abbreviation = match.group(1)
            if abbreviation in seen or abbreviation.upper() in known:
                continue
            seen.add(abbreviation)
            tail = line[match.end() : match.end() + 120]
            if not EXPANSION_RE.search(tail):
                found.append(
                    (number, f"Аббревиатура «{abbreviation}» не расшифрована при первом употреблении", abbreviation)
                )
    return found


def rule_image_alt(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """У изображения должен быть alt-текст и подпись."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    found = []
    for index, line in enumerate(lines):
        for alt, src, title in IMAGE_RE.findall(line):
            number = index + 1
            if not alt.strip():
                found.append((number, f"У изображения {src} нет alt-текста", src))
            caption = title.strip() or (lines[index + 1].strip() if index + 1 < len(lines) else "")
            if not caption or caption.startswith(("#", "```")):
                found.append((number, f"У изображения {src} нет подписи", src))
    return found


def rule_escalation(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Открытый вопрос разбора: нужен ли в troubleshooting раздел с эскалацией."""
    lowered = (text or "").lower()
    if "эскалац" in lowered or "обратитесь в техническую поддержку" in lowered:
        return []
    return [(0, "Нет раздела об эскалации: куда обращаться, если решение не помогло", "")]


def rule_crosslocale(text: str, context: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Для сверки языковых версий нужен article_id."""
    meta = profile_rules.meta_fields(text)
    if str(meta.get("article_id", "")).strip():
        return []
    return [(1, "Нет article_id — статью нельзя сверить с версиями на других языках", "")]


RULES: dict[str, Callable[[str, dict[str, Any]], list[tuple[int, str, str]]]] = {
    "KDOC-ADMONITION-TYPE": rule_admonition_type,
    "KDOC-LEADIN": rule_leadin,
    "KDOC-RESULT": rule_result,
    "KDOC-UI-BOLD": rule_ui_bold,
    "KDOC-TABLE-FOR-PARALLEL": rule_table_for_parallel,
    "KDOC-FOOTER-META": rule_footer_meta,
    "KDOC-ABBR-EXPANSION": rule_abbr_expansion,
    "KDOC-IMAGE-ALT": rule_image_alt,
    "KDOC-ESCALATION": rule_escalation,
    "KDOC-CROSSLOCALE": rule_crosslocale,
}

# Правила, которые имеют смысл только для документа целиком.
DOCUMENT_ONLY = {"KDOC-FOOTER-META", "KDOC-CROSSLOCALE", "KDOC-ESCALATION", "KDOC-RESULT"}

# Правила, привязанные к профилям шаблона (кроме заданного в docs-config).
PROFILE_BOUND = {"KDOC-FOOTER-META": {"modern_help", "modern_kb"}}


def check(
    text: str,
    config: dict[str, Any],
    profile: str,
    type_id: str,
    scope: str = "document",
) -> list[Any]:
    """Прогоняет включённые KDOC-правила, применимые к этому типу и профилю."""
    from . import Violation

    rules = docs_config.kdoc_rules(config)
    if not rules:
        return []

    type_entry = docs_config.type_by_id(config, type_id) if type_id else None
    type_overrides = (type_entry or {}).get("rules", {})

    context = {
        "admonition_types": docs_config.admonition_types(config),
        "glossary": docs_config.glossary(config),
        "profile": profile,
        "type_id": type_id,
    }

    violations: list[Violation] = []
    for rule_id, handler in RULES.items():
        settings = rules.get(rule_id)
        if not settings or not settings.get("enabled", True):
            continue
        if scope == "section" and rule_id in DOCUMENT_ONLY:
            continue

        bound_types = settings.get("types") or []
        if bound_types and type_id and type_id not in bound_types:
            continue
        if bound_types and not type_id:
            continue
        bound_profiles = set(settings.get("profiles") or []) or PROFILE_BOUND.get(rule_id)
        if bound_profiles and profile and profile not in bound_profiles:
            continue

        severity = str(type_overrides.get(rule_id, settings.get("severity", "warning")))
        kind = "recommendation" if severity != "error" else "violation"

        for line, message, excerpt in handler(text, context):
            violations.append(
                Violation("kdoc", rule_id, severity, line, message, excerpt, kind=kind)
            )
    return violations
