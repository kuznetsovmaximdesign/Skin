"""Разбор образцов документации: сервис сам выводит формат по готовым файлам.

Сначала считается детерминированный профиль (заголовки, списки, длины, обращение,
формат дат) — быстро и без модели. Затем, если нужно, локальная модель формулирует
по этому профилю короткие правила словами.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .ollama_client import OllamaClient

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*([-*+])\s+\S")
ORDERED_RE = re.compile(r"^\s*\d+([.)])\s+\S")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DOTTED_DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
VERSION_RE = re.compile(r"\bверси[яию]\s+\d+(\.\d+)*", re.IGNORECASE)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
LINK_RE = re.compile(r"\[[^\]]+\]\([^)\s]+\)")

MAX_SAMPLE_CHARS = 20000  # образцы читаем по одному и обрезаем: память бережём


def read_sample(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:MAX_SAMPLE_CHARS]


def analyze_samples(paths: list[Path]) -> dict[str, Any]:
    """Считает профиль оформления по образцам. Файлы читаются по одному."""
    stats = {
        "files": [],
        "documents": 0,
        "bullets": Counter(),
        "ordered": Counter(),
        "headings_per_level": Counter(),
        "top_sections": Counter(),
        "section_orders": [],
        "sentences": [],
        "paragraph_sentences": [],
        "you_formal": 0,
        "you_informal": 0,
        "we": 0,
        "iso_dates": 0,
        "dotted_dates": 0,
        "versions": 0,
        "inline_code": 0,
        "links": 0,
        "tables": 0,
        "code_blocks": 0,
        "code_blocks_with_lang": 0,
        "exclamations": 0,
        "heading_sentence_case": 0,
        "heading_title_case": 0,
    }

    for path in paths:
        text = read_sample(path)
        if not text.strip():
            continue
        stats["documents"] += 1
        stats["files"].append(path.name)
        _collect(text, stats)

    return _summarize(stats)


def _collect(text: str, stats: dict[str, Any]) -> None:
    lines = text.replace("\r\n", "\n").split("\n")
    in_fence = False
    doc_sections: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            if in_fence:
                stats["code_blocks"] += 1
                if len(stripped) > 3:
                    stats["code_blocks_with_lang"] += 1
            continue
        if in_fence:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            stats["headings_per_level"][level] += 1
            if level == 2:
                doc_sections.append(title)
                stats["top_sections"][title] += 1
            words = [word for word in title.split() if word.isalpha()]
            if len(words) > 1:
                if all(word.islower() for word in words[1:]):
                    stats["heading_sentence_case"] += 1
                else:
                    stats["heading_title_case"] += 1
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            stats["bullets"][bullet.group(1)] += 1
        ordered = ORDERED_RE.match(line)
        if ordered:
            stats["ordered"][ordered.group(1)] += 1
        if stripped.startswith("|"):
            stats["tables"] += 1

    if doc_sections:
        stats["section_orders"].append(doc_sections)

    prose = _prose_only(text)
    stats["you_formal"] += len(re.findall(r"\b[Вв]ы\b|\b[Вв]ам\b|\b[Вв]ас\b", prose))
    stats["you_informal"] += len(re.findall(r"\b[Тт]ы\b|\b[Тт]ебе\b|\b[Тт]ебя\b", prose))
    stats["we"] += len(re.findall(r"\b[Мм]ы\b", prose))
    stats["iso_dates"] += len(ISO_DATE_RE.findall(prose))
    stats["dotted_dates"] += len(DOTTED_DATE_RE.findall(prose))
    stats["versions"] += len(VERSION_RE.findall(prose))
    stats["inline_code"] += len(INLINE_CODE_RE.findall(prose))
    stats["links"] += len(LINK_RE.findall(prose))
    stats["exclamations"] += prose.count("!")

    for paragraph in re.split(r"\n\s*\n", prose):
        body = paragraph.strip()
        if not body or body.startswith(("#", "|", "-", "*", ">")) or ORDERED_RE.match(body):
            continue
        sentences = [s for s in SENTENCE_SPLIT_RE.split(body) if s.strip()]
        if not sentences:
            continue
        stats["paragraph_sentences"].append(len(sentences))
        for sentence in sentences:
            stats["sentences"].append(len(sentence.split()))


def _prose_only(text: str) -> str:
    """Текст без блоков кода — иначе статистика врёт."""
    return re.sub(r"```.*?```", " ", text, flags=re.DOTALL)


def _summarize(stats: dict[str, Any]) -> dict[str, Any]:
    sentences = stats["sentences"]
    paragraphs = stats["paragraph_sentences"]
    documents = stats["documents"]

    def common_marker(counter: Counter, default: str) -> str:
        return counter.most_common(1)[0][0] if counter else default

    # Разделы, которые встречаются больше чем в половине образцов, в типичном порядке.
    threshold = max(1, documents // 2 + documents % 2)
    frequent = [title for title, count in stats["top_sections"].items() if count >= threshold]
    order: list[str] = []
    for sections in stats["section_orders"]:
        for title in sections:
            if title in frequent and title not in order:
                order.append(title)

    return {
        "documents": documents,
        "files": stats["files"],
        "bullet_marker": common_marker(stats["bullets"], "-"),
        "ordered_marker": common_marker(stats["ordered"], "."),
        "typical_sections": order,
        "avg_sentence_words": round(sum(sentences) / len(sentences), 1) if sentences else 0,
        "max_sentence_words": max(sentences) if sentences else 0,
        "avg_paragraph_sentences": round(sum(paragraphs) / len(paragraphs), 1) if paragraphs else 0,
        "address": "вы" if stats["you_formal"] >= stats["you_informal"] else "ты",
        "uses_we": stats["we"] > documents,
        "date_format": (
            "ГГГГ-ММ-ДД" if stats["iso_dates"] > stats["dotted_dates"]
            else "ДД.ММ.ГГГГ" if stats["dotted_dates"] else ""
        ),
        "versions_spelled": stats["versions"] > 0,
        "uses_inline_code": stats["inline_code"] > documents,
        "uses_tables": stats["tables"] > 0,
        "code_blocks": stats["code_blocks"],
        "code_blocks_with_lang": stats["code_blocks_with_lang"],
        "uses_links": stats["links"] > 0,
        "exclamations": stats["exclamations"],
        "heading_case": (
            "с заглавной только первое слово"
            if stats["heading_sentence_case"] >= stats["heading_title_case"]
            else "каждое слово с заглавной"
        ),
    }


def profile_to_markdown(profile: dict[str, Any]) -> str:
    """Профиль → правила словами. Это то, что уходит в модель и видит писатель."""
    if not profile.get("documents"):
        return ""

    rules: list[str] = []
    if profile["typical_sections"]:
        rules.append(
            "Порядок разделов как в образцах: " + " → ".join(profile["typical_sections"]) + "."
        )
    rules.append(f"Обращение к читателю — на «{profile['address']}».")
    if not profile["uses_we"]:
        rules.append("Не писать от первого лица («мы сделали»).")
    if profile["avg_sentence_words"]:
        limit = max(12, round(profile["avg_sentence_words"] * 1.4))
        rules.append(
            f"Предложения короткие: в образцах в среднем {profile['avg_sentence_words']} слов, "
            f"держаться в пределах {limit}."
        )
    if profile["avg_paragraph_sentences"]:
        rules.append(
            f"Абзац — примерно {profile['avg_paragraph_sentences']} предложения, длинные абзацы разбивать."
        )
    rules.append(f"Маркированные списки — символом «{profile['bullet_marker']}».")
    rules.append(
        "Нумерованные списки — в формате «1"
        + profile["ordered_marker"]
        + "»."
    )
    rules.append(f"Заголовки: {profile['heading_case']}.")
    if profile["uses_inline_code"]:
        rules.append("Названия параметров, файлов и команд — в обратных кавычках.")
    if profile["date_format"]:
        rules.append(f"Даты в формате {profile['date_format']}.")
    if profile["versions_spelled"]:
        rules.append("Версии писать словом «версия» и числом полностью.")
    if profile["uses_tables"]:
        rules.append("Таблицы оформлять Markdown-таблицами, как в образцах.")
    if profile["code_blocks"] and profile["code_blocks_with_lang"] >= profile["code_blocks"] / 2:
        rules.append("У блоков кода указывать язык после открывающих кавычек.")
    if profile["exclamations"] == 0:
        rules.append("Без восклицательных знаков.")

    header = (
        "# Формат, выведенный из образцов\n\n"
        f"Разобрано документов: {profile['documents']} ({', '.join(profile['files'])}).\n\n"
    )
    return header + "\n".join(f"- {rule}" for rule in rules) + "\n"


DERIVE_SYSTEM = """Ты — редактор, который описывает правила оформления документации по образцам.

Правила ответа:
1. Верни только маркированный список правил, без вступления и выводов.
2. Пиши правила, которые видно в образцах: структура, тон, длина предложений, оформление списков,
   терминов, кода, таблиц, дат и версий.
3. Не выдумывай правил, которых в образцах нет.
4. Не более 12 правил, каждое — одна короткая строка на русском."""


def build_derive_prompt(profile: dict[str, Any], excerpts: list[str]) -> str:
    measured = profile_to_markdown(profile) or "(измеримых признаков не найдено)"
    body = "\n\n---\n\n".join(excerpts)
    return f"""# ИЗМЕРЕННЫЕ ПРИЗНАКИ ОБРАЗЦОВ

{measured}

# ФРАГМЕНТЫ ОБРАЗЦОВ

{body}

# ЗАДАНИЕ

Опиши правила оформления, которым следуют эти документы, маркированным списком."""


def derive_rules_with_model(
    config: dict[str, Any],
    client: OllamaClient,
    profile: dict[str, Any],
    excerpts: list[str],
) -> str:
    """Необязательный проход модели: формулирует правила словами по образцам."""
    model = config["ollama"]["generation_model"]
    client.ensure_model(model)
    return client.generate(
        model=model,
        prompt=build_derive_prompt(profile, excerpts),
        system=DERIVE_SYSTEM,
        temperature=float(config["generation"]["temperature"]),
        num_ctx=int(config["generation"]["num_ctx"]),
    )
