"""Карта «документ ↔ что он документирует».

Для каждого документа один раз считается короткое резюме: какие функции и сущности он
описывает. Резюме хранится в индексе и используется при выборе целевого документа —
смысловая связь точнее совпадения слов.

Порядок работы бережёт память: сначала все резюме пишет модель генерации, затем она
выгружается, и только потом считаются эмбеддинги.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import index_store, indexer
from .config import resolve_path
from .ollama_client import OllamaClient

SUMMARY_SYSTEM = """Ты — технический аналитик. По документу ты пишешь очень короткую справку о том, что он документирует.

Формат ответа — ровно две строки:
ОПИСАНИЕ: <одно-два предложения: какую функциональность и для кого описывает документ>
СУЩНОСТИ: <до семи ключевых сущностей через запятую: функции, объекты, параметры, роли>

Не пересказывай содержание, не выдумывай того, чего в документе нет."""

DESCRIPTION_RE = re.compile(r"^\s*ОПИСАНИЕ:\s*(.+)$", re.MULTILINE)
ENTITIES_RE = re.compile(r"^\s*СУЩНОСТИ:\s*(.+)$", re.MULTILINE)

MAX_DOC_CHARS = 6000  # в модель уходит начало документа: этого хватает для справки


def build_prompt(title: str, text: str) -> str:
    return f"""# ДОКУМЕНТ: {title}

{text[:MAX_DOC_CHARS]}

# ЗАДАНИЕ

Напиши, что документирует этот документ, в требуемом формате из двух строк."""


def parse(answer: str) -> tuple[str, str]:
    description = DESCRIPTION_RE.search(answer or "")
    entities = ENTITIES_RE.search(answer or "")
    summary = description.group(1).strip() if description else (answer or "").strip().split("\n")[0]
    return summary[:500], (entities.group(1).strip() if entities else "")[:300]


def build_map(config: dict[str, Any], client: OllamaClient, force: bool = False) -> dict[str, Any]:
    """Досчитывает резюме для документов, у которых его ещё нет."""
    index_file = indexer.index_path(config)
    if not index_store.exists(index_file):
        return {"built": 0, "skipped": 0, "documents": []}

    docs_dir = resolve_path(config["paths"]["docs_dir"])
    generation_model = config["ollama"]["generation_model"]
    embedding_model = config["ollama"]["embedding_model"]

    with index_store.connect(index_file) as connection:
        if force:
            paths = [document["path"] for document in index_store.documents(connection)]
        else:
            paths = index_store.documents_without_summary(connection)
        titles = {
            document["path"]: document["title"] for document in index_store.documents(connection)
        }

    if not paths:
        return {"built": 0, "skipped": 0, "documents": []}

    # Шаг 1: модель генерации пишет справки.
    client.ensure_model(generation_model)
    prepared: list[tuple[str, str, str]] = []
    for path in paths:
        file_path = docs_dir / path
        if not file_path.exists():
            continue
        answer = client.generate(
            model=generation_model,
            prompt=build_prompt(titles.get(path, path), indexer.read_text(file_path)),
            system=SUMMARY_SYSTEM,
            temperature=float(config["generation"]["temperature"]),
            num_ctx=int(config["generation"]["num_ctx"]),
        )
        summary, entities = parse(answer)
        if summary:
            prepared.append((path, summary, entities))

    # Шаг 2: модель генерации больше не нужна — освобождаем память под эмбеддинги.
    if config["ollama"].get("sequential_models", True):
        client.unload(generation_model)

    vectors: list[list[float]] = []
    if prepared:
        client.ensure_model(embedding_model)
        batch_size = max(1, int(config["search"].get("embed_batch", 8)))
        inputs = [f"{summary} {entities}" for _, summary, entities in prepared]
        for start in range(0, len(inputs), batch_size):
            vectors.extend(client.embed(embedding_model, inputs[start : start + batch_size]))

    with index_store.connect(index_file) as connection:
        for (path, summary, entities), vector in zip(prepared, vectors):
            index_store.set_summary(
                connection, path, summary, entities, index_store.pack(vector) if vector else None
            )

    return {
        "built": len(prepared),
        "skipped": len(paths) - len(prepared),
        "documents": [
            {"path": path, "summary": summary, "entities": entities}
            for path, summary, entities in prepared
        ],
    }


def read_map(config: dict[str, Any]) -> list[dict[str, Any]]:
    index_file: Path = indexer.index_path(config)
    if not index_store.exists(index_file):
        return []
    with index_store.connect(index_file) as connection:
        return [
            {
                "path": document["path"],
                "title": document["title"],
                "summary": document["summary"],
                "entities": document["entities"],
            }
            for document in index_store.documents(connection)
        ]
