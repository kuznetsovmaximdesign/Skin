"""Сборка промпта и генерация обновлённого документа локальной моделью."""

from __future__ import annotations

from typing import Any

from .ollama_client import OllamaClient

MAX_GUIDE_CHARS = 12000
# Грубая оценка: для русского текста примерно 3 символа на токен.
CHARS_PER_TOKEN = 3

SYSTEM_PROMPT = """Ты — технический редактор документации. Ты обновляешь существующие Markdown-документы.

Железные правила:
1. Возвращай ПОЛНЫЙ обновлённый документ целиком, от первой строки до последней. Не пиши фрагменты, комментарии, объяснения или списки правок.
2. Сохраняй исходную структуру: те же заголовки, их порядок и уровни, таблицы, списки, блоки кода, ссылки. Новый раздел добавляй только если без него описанное изменение некуда поместить.
3. Меняй только то, что затронуто описанием изменения. Остальной текст переноси дословно.
4. Не выдумывай факты: версии, числа, имена, названия параметров, даты. Если данных не хватает — вставь прямо в текст пометку [уточнить] (при необходимости с коротким вопросом, например «[уточнить: номер версии]»).
5. Гайд по стилю имеет приоритет. Если описание изменения противоречит гайду — следуй гайду и пометь спорное место как [спорно: краткое описание конфликта].
6. Пиши на языке исходного документа.
7. Ответ — только Markdown документа. Без ``` вокруг всего ответа, без вступлений вроде «Вот обновлённый документ»."""


def build_prompt(document: str, change_description: str, style_guide: str, doc_path: str) -> str:
    guide = (style_guide or "").strip()
    if len(guide) > MAX_GUIDE_CHARS:
        guide = guide[:MAX_GUIDE_CHARS] + "\n\n[гайд обрезан по длине]"
    if not guide:
        guide = "(гайд по стилю не подключён — сохраняй стиль исходного документа)"

    return f"""# ГАЙД ПО СТИЛЮ (обязателен к соблюдению)

{guide}

# ИСХОДНЫЙ ДОКУМЕНТ ({doc_path})

{document}

# ЧТО ИЗМЕНИЛОСЬ / ЧТО НУЖНО ОТРАЗИТЬ

{change_description.strip()}

# ЗАДАНИЕ

Внеси описанное изменение в исходный документ по правилам гайда по стилю.
Верни полный обновлённый Markdown-документ и ничего кроме него."""


def generate_update(
    config: dict[str, Any],
    client: OllamaClient,
    document: str,
    change_description: str,
    style_guide: str,
    doc_path: str,
) -> dict[str, Any]:
    model = config["ollama"]["generation_model"]
    client.ensure_model(model)

    num_ctx = int(config["generation"]["num_ctx"])
    prompt = build_prompt(document, change_description, style_guide, doc_path)
    size_warnings = check_context_size(prompt, document, num_ctx)
    updated = client.generate(
        model=model,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        temperature=float(config["generation"]["temperature"]),
        num_ctx=num_ctx,
    )

    return {
        "content": updated,
        "warnings": size_warnings + check_result(document, updated),
        "model": model,
    }


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def check_context_size(prompt: str, document: str, num_ctx: int) -> list[str]:
    """Модель должна вместить и запрос, и ответ. Если не влезает — предупреждаем заранее."""
    needed = estimate_tokens(prompt) + estimate_tokens(document)
    if needed <= num_ctx:
        return []
    return [
        f"Документ и гайд не помещаются в окно модели: нужно примерно {needed} токенов, "
        f"а в config.yaml указано num_ctx: {num_ctx}. Увеличьте `generation.num_ctx` "
        "или сократите гайд — иначе часть документа может потеряться."
    ]


def check_result(original: str, updated: str) -> list[str]:
    """Простые проверки результата — чтобы писатель сразу видел риск потери текста."""
    warnings: list[str] = []
    if not updated.strip():
        warnings.append("Модель вернула пустой ответ. Попробуйте переформулировать описание изменения.")
        return warnings

    if len(updated) < len(original) * 0.6:
        warnings.append(
            "Обновлённый документ заметно короче исходного — проверьте, не потерялись ли разделы."
        )

    original_headings = [line.strip() for line in original.splitlines() if line.strip().startswith("#")]
    updated_headings = {line.strip() for line in updated.splitlines() if line.strip().startswith("#")}
    lost = [heading for heading in original_headings if heading not in updated_headings]
    if lost:
        preview = ", ".join(lost[:5])
        warnings.append(f"В результате не найдены исходные заголовки: {preview}")

    if "[уточнить]" in updated or "[уточнить:" in updated:
        warnings.append("В документе есть пометки [уточнить] — данных не хватило, проверьте их вручную.")
    if "[спорно:" in updated:
        warnings.append("Есть пометки [спорно: …] — правка конфликтует с гайдом по стилю.")
    return warnings
