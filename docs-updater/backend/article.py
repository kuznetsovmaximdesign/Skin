"""Генерация новой статьи по шаблону продукта.

Статья собирается по разделам шаблона, а не свободным текстом: сервис знает, какие
разделы обязательны, в каком порядке и какого уровня. Факты берутся только из требований;
где данных нет — ставится пометка [уточнить].

Готовый черновик проходит тот же модуль проверки соответствия, что и правки
(backend/verify.check_and_fix) — второй копии проверки в проекте нет.
"""

from __future__ import annotations

from typing import Any

from . import docs_config
from .checks import schema as schema_rules
from .ollama_client import OllamaClient

MAX_REQUIREMENTS_CHARS = 12000
MAX_EXAMPLE_CHARS = 1500

SECTION_SYSTEM = """Ты — технический писатель. Ты пишешь ОДИН раздел новой статьи документации.

Железные правила:
1. Верни только текст этого раздела, начиная с его заголовка нужного уровня.
2. Пиши строго по требованиям. Не выдумывай фактов: версий, чисел, имён, параметров, сроков.
3. Если для раздела не хватает данных — напиши короткую строку с пометкой [уточнить] и вопросом, чего не хватает.
4. Соблюдай правила оформления из гайда.
5. Другие разделы не пиши и не повторяй. Без вступлений и без ``` вокруг ответа."""


def template_sections(config: dict[str, Any], type_id: str = "") -> list[tuple[str, int]]:
    """Разделы шаблона: сначала схема выбранного типа статьи, иначе общий шаблон продукта."""
    entry = docs_config.type_by_id(config, type_id) if type_id else None
    if entry:
        levels = entry["section_levels"]
        ordered = list(entry["required_sections"])
        for title in entry.get("optional_sections", []):
            if title not in ordered:
                ordered.append(title)
        return [(title, int(levels.get(title, 2))) for title in ordered]

    settings = config.get("checks", {}) or {}
    template = schema_rules.load_schema(config, settings)
    levels = template.get("section_levels") or {}
    required = template.get("required_sections") or []
    ordered = list(required)
    for title in levels:
        if title not in ordered:
            ordered.append(title)
    return [(title, int(levels.get(title, 2))) for title in ordered]


def front_matter_block(
    config: dict[str, Any], values: dict[str, str], type_id: str = "", profile: str = ""
) -> str:
    """Блок метаданных: обязательные поля типа статьи для выбранного профиля шаблона."""
    entry = docs_config.type_by_id(config, type_id) if type_id else None
    fields: list[str] = []
    if entry:
        fields = docs_config.required_meta_for(entry, profile)
    if not fields:
        settings = config.get("checks", {}) or {}
        template = schema_rules.load_schema(config, settings)
        fields = list(template.get("front_matter") or [])
    if not fields and not type_id:
        return ""

    lines = ["---"]
    if type_id:
        lines.append(f"type_id: {type_id}")
        if profile:
            lines.append(f"template_profile: {profile}")
    for field in fields:
        lines.append(f"{field}: {values.get(field, '[уточнить]')}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def build_section_prompt(
    title: str,
    level: int,
    article_title: str,
    requirements: str,
    style_guide: str,
    outline: list[str],
    example: str,
) -> str:
    guide = (style_guide or "").strip() or "(гайд не подключён — пиши нейтрально и единообразно)"
    example_block = (
        f"# ПРИМЕР ТОНА ИЗ СУЩЕСТВУЮЩЕЙ ДОКУМЕНТАЦИИ (только манера изложения, факты не копировать)\n\n"
        f"{example[:MAX_EXAMPLE_CHARS]}\n\n"
        if example
        else ""
    )
    return f"""# ПРАВИЛА ОФОРМЛЕНИЯ

{guide}

# СТАТЬЯ: {article_title}

Разделы статьи по шаблону продукта: {", ".join(outline)}.

{example_block}# ТРЕБОВАНИЯ К ФУНКЦИОНАЛУ

{requirements[:MAX_REQUIREMENTS_CHARS]}

# ЗАДАНИЕ

Напиши раздел «{title}» заголовком уровня {level} ({"#" * level} {title}).
Только этот раздел, строго по требованиям."""


def draft(
    config: dict[str, Any],
    client: OllamaClient,
    title: str,
    requirements: str,
    style_guide: str,
    example: str = "",
    front_matter: dict[str, str] | None = None,
    type_id: str = "",
    profile: str = "",
) -> dict[str, Any]:
    """Собирает черновик статьи по разделам шаблона выбранного типа."""
    model = config["ollama"]["generation_model"]
    client.ensure_model(model)

    plan = template_sections(config, type_id)
    if not plan:
        plan = [("Назначение", 2), ("Ограничения", 2)]
    outline = [name for name, _ in plan]

    parts: list[str] = [f"# {title}\n"]
    for name, level in plan:
        answer = client.generate(
            model=model,
            prompt=build_section_prompt(name, level, title, requirements, style_guide, outline, example),
            system=SECTION_SYSTEM,
            temperature=float(config["generation"]["temperature"]),
            num_ctx=int(config["generation"]["num_ctx"]),
        )
        body = (answer or "").strip()
        if not body:
            body = f"{'#' * level} {name}\n\n[уточнить] требования не описывают этот раздел."
        if not body.lstrip().startswith("#"):
            body = f"{'#' * level} {name}\n\n{body}"
        parts.append(body)

    body = "\n\n".join(part.strip() for part in parts if part.strip()) + "\n"

    # Если тип не задан явно, определяем его по собранной структуре: от типа и профиля
    # зависит, какие метаполя обязательны в этой статье.
    if not type_id:
        from .checks import describe_document

        described = describe_document(body, config)
        type_id = described["type_id"]
        profile = profile or described["profile"]

    return {
        "text": front_matter_block(config, front_matter or {}, type_id, profile) + body,
        "sections": outline,
        "type_id": type_id,
        "profile": profile,
    }
