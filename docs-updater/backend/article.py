"""Генерация новой статьи по шаблону продукта.

Статья собирается по разделам шаблона, а не свободным текстом: сервис знает, какие
разделы обязательны, в каком порядке и какого уровня. Факты берутся только из требований;
где данных нет — ставится пометка [уточнить].

Готовый черновик проходит тот же модуль проверки соответствия, что и правки
(backend/verify.check_and_fix) — второй копии проверки в проекте нет.
"""

from __future__ import annotations

from typing import Any

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


def template_sections(config: dict[str, Any]) -> list[tuple[str, int]]:
    """Разделы шаблона продукта и их уровни."""
    settings = config.get("checks", {}) or {}
    template = schema_rules.load_schema(config, settings)
    levels = template.get("section_levels") or {}
    required = template.get("required_sections") or []
    ordered = list(required)
    for title in levels:
        if title not in ordered:
            ordered.append(title)
    return [(title, int(levels.get(title, 2))) for title in ordered]


def front_matter_block(config: dict[str, Any], values: dict[str, str]) -> str:
    settings = config.get("checks", {}) or {}
    template = schema_rules.load_schema(config, settings)
    fields = template.get("front_matter") or []
    if not fields:
        return ""
    lines = ["---"]
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
) -> dict[str, Any]:
    """Собирает черновик статьи по разделам шаблона."""
    model = config["ollama"]["generation_model"]
    client.ensure_model(model)

    plan = template_sections(config)
    if not plan:
        plan = [("Назначение", 2), ("Ограничения", 2)]
    outline = [name for name, _ in plan]

    parts: list[str] = [front_matter_block(config, front_matter or {}) + f"# {title}\n"]
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

    return {"text": "\n\n".join(part.strip() for part in parts if part.strip()) + "\n", "sections": outline}
