"""Автосвязывание: какие статьи затронуты изменением.

Кандидаты подбираются локальным поиском по карте «документ ↔ что он документирует»
и по секциям, затем модель классифицирует каждую: дополнить / заменить / устарело.
Работает в пределах одного продукта — карта и индекс у каждого свои.
"""

from __future__ import annotations

import re
from typing import Any

from . import indexer, search
from .ollama_client import OllamaClient

CLASSES = {"дополнить", "заменить", "устарело"}

IMPACT_SYSTEM = """Ты — редактор документации. Тебе дают описание изменения и краткую справку о документе.

Ответь ровно двумя строками:
КЛАСС: <дополнить | заменить | устарело>
ПРИЧИНА: <одно предложение, почему именно так>

Значения классов:
- дополнить — в документ нужно добавить описание нового поведения;
- заменить — описанное в документе поведение изменилось, текст надо переписать;
- устарело — документ описывает то, чего больше нет.

Если изменение документа не касается, ответь КЛАСС: дополнить и ПРИЧИНА: изменение документа не касается."""

CLASS_RE = re.compile(r"^\s*КЛАСС:\s*(.+)$", re.MULTILINE)
REASON_RE = re.compile(r"^\s*ПРИЧИНА:\s*(.+)$", re.MULTILINE)


def build_prompt(description: str, candidate: dict[str, Any]) -> str:
    summary = candidate.get("summary") or candidate.get("snippet") or ""
    return f"""# ОПИСАНИЕ ИЗМЕНЕНИЯ

{description}

# ДОКУМЕНТ

Название: {candidate.get('title', '')}
Файл: {candidate.get('path', '')}
Что документирует: {summary}
Сущности: {candidate.get('entities', '')}
Ближайший раздел: {candidate.get('heading', '')}

# ЗАДАНИЕ

Классифицируй, что нужно сделать с этим документом."""


def parse(answer: str) -> tuple[str, str]:
    found = CLASS_RE.search(answer or "")
    reason = REASON_RE.search(answer or "")
    label = (found.group(1).strip().lower() if found else "").strip(".:; ")
    label = next((item for item in CLASSES if item in label), "дополнить")
    return label, (reason.group(1).strip() if reason else "")


def analyze(
    config: dict[str, Any],
    client: OllamaClient,
    description: str,
    top_k: int = 8,
    threshold: int = 45,
) -> dict[str, Any]:
    """Возвращает все затронутые статьи с классификацией и причиной, по убыванию релевантности."""
    if not indexer.index_exists(config):
        return {"documents": [], "summary": {"total": 0, "note": "индекс пуст"}}

    candidates = search.search_documents(indexer.index_path(config), client, description, top_k)
    relevant = [item for item in candidates if item["relevance"] >= threshold]

    model = config["ollama"]["generation_model"]
    if relevant:
        client.ensure_model(model)

    results: list[dict[str, Any]] = []
    for candidate in relevant:
        answer = client.generate(
            model=model,
            prompt=build_prompt(description, candidate),
            system=IMPACT_SYSTEM,
            temperature=float(config["generation"]["temperature"]),
            num_ctx=int(config["generation"]["num_ctx"]),
        )
        label, reason = parse(answer)
        results.append(
            {
                "path": candidate["path"],
                "title": candidate["title"],
                "summary": candidate.get("summary", ""),
                "heading": candidate.get("heading", ""),
                "matched_on": candidate.get("matched_on", "section"),
                "relevance": candidate["relevance"],
                "action": label,
                "reason": reason,
            }
        )

    results.sort(key=lambda item: item["relevance"], reverse=True)
    return {
        "documents": results,
        "summary": {
            "total": len(results),
            "considered": len(candidates),
            "by_action": {
                label: sum(1 for item in results if item["action"] == label)
                for label in sorted({item["action"] for item in results})
            },
        },
    }
