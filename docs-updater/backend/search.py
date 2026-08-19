"""Локальный семантический поиск по индексу: косинусная близость, без внешних библиотек."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import index_store
from .ollama_client import OllamaClient


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def to_percent(score: float) -> int:
    """Косинус [-1..1] → процент релевантности для интерфейса."""
    return max(0, min(100, round((score + 1) / 2 * 100)))


def search_documents(
    index_file: Path,
    client: OllamaClient,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Семантический поиск по индексу.

    Векторы читаются курсором по одной строке, тексты секций подтягиваются только
    для документов-победителей — в памяти всё время лежит несколько сотен килобайт.
    """
    if not index_store.exists(index_file):
        return []

    with index_store.connect(index_file) as connection:
        model = index_store.get_meta(connection, "embedding_model")
        query_vector = client.embed(model, [query])[0]

        best: dict[str, dict[str, Any]] = {}
        for section_id, doc_path, doc_title, heading, vector in index_store.iter_embeddings(connection):
            score = cosine(query_vector, vector)
            current = best.get(doc_path)
            if current is None or score > current["score"]:
                best[doc_path] = {
                    "id": section_id,
                    "path": doc_path,
                    "title": doc_title or doc_path,
                    "heading": heading or "",
                    "score": score,
                }

        ranked = sorted(best.values(), key=lambda item: item["score"], reverse=True)[:top_k]
        return [
            {
                "path": item["path"],
                "title": item["title"],
                "heading": item["heading"],
                "snippet": snippet(index_store.section_text(connection, item["id"])),
                "relevance": to_percent(item["score"]),
                "score": round(item["score"], 4),
            }
            for item in ranked
        ]


def snippet(text: str, limit: int = 220) -> str:
    body = " ".join(line for line in text.splitlines() if not line.startswith("#")).strip()
    body = " ".join(body.split())
    return body[:limit] + ("…" if len(body) > limit else "")
