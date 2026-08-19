"""Кросс-локальная сверка статей.

`article_id` связывает языковые версии одной статьи. Проверяются две разные вещи,
и смешивать их нельзя:

- **структурный паритет** — совпадает ли состав и порядок заголовков;
- **рассинхрон даты и версии** — одинаковый `article_id` и даже одинаковая структура
  не означают, что версии обновляли вместе.

Учтено, что часть контента рыночно-специфична: тип, помеченный `market_specific`,
не обязан иметь зеркало во всех локалях, и его отсутствие не считается расхождением.
"""

from __future__ import annotations

from typing import Any

from . import docs_config, indexer, languages
from .checks import article_types, profiles as profile_rules
from .config import resolve_path


def article_key(text: str) -> str:
    meta = profile_rules.meta_fields(text)
    return str(meta.get("article_id", "")).strip()


def structure_of(text: str) -> list[int]:
    """Форма документа: последовательность уровней заголовков.

    Заголовки в локалях переведены, поэтому сравнивать их дословно нельзя —
    структурный паритет означает одинаковый состав и порядок уровней.
    """
    return [level for _, level, _ in article_types.outline(text)]


def collect(config: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Все языковые версии по article_id: {article_id: {язык: сведения}}."""
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    known = [languages.source_language(config), *languages.target_languages(config)]
    grouped: dict[str, dict[str, dict[str, Any]]] = {}

    for path in indexer.find_markdown_files(docs_dir):
        relative = path.relative_to(docs_dir)
        text = indexer.read_text(path)
        key = article_key(text)
        if not key:
            continue

        parts = relative.parts
        language = parts[0] if parts and parts[0] in known else languages.source_language(config)
        meta = profile_rules.meta_fields(text)
        detected = article_types.detect_type(config, text)

        grouped.setdefault(key, {})[language] = {
            "path": relative.as_posix(),
            "language": language,
            "structure": structure_of(text),
            "updated": str(meta.get("updated", "")).strip(),
            "version": str(meta.get("version", "")).strip(),
            "type_id": detected["type_id"],
        }
    return grouped


def compare(config: dict[str, Any]) -> dict[str, Any]:
    """Расхождения между языковыми версиями: структура и даты — раздельно."""
    grouped = collect(config)
    source_language = languages.source_language(config)
    findings: list[dict[str, Any]] = []
    articles: list[dict[str, Any]] = []

    for key, versions in sorted(grouped.items()):
        base_language = source_language if source_language in versions else sorted(versions)[0]
        base = versions[base_language]
        entry = docs_config.type_by_id(config, base["type_id"]) if base["type_id"] else None
        market_specific = bool((entry or {}).get("market_specific"))

        article: dict[str, Any] = {
            "article_id": key,
            "languages": sorted(versions),
            "base_language": base_language,
            "type_id": base["type_id"],
            "market_specific": market_specific,
            "structure_equal": True,
            "dates_equal": True,
        }

        for language, version in sorted(versions.items()):
            if language == base_language:
                continue

            if version["structure"] != base["structure"]:
                article["structure_equal"] = False
                findings.append(
                    {
                        "kind": "structure-mismatch",
                        "severity": "warning",
                        "article_id": key,
                        "language": language,
                        "path": version["path"],
                        "message": (
                            f"Структура версии «{language}» не совпадает с «{base_language}»: "
                            f"{len(version['structure'])} заголовков против {len(base['structure'])}"
                        ),
                    }
                )

            # Совпадение структуры не значит синхронного обновления — даты проверяем отдельно.
            if base["updated"] and version["updated"] and base["updated"] != version["updated"]:
                article["dates_equal"] = False
                findings.append(
                    {
                        "kind": "date-mismatch",
                        "severity": "warning",
                        "article_id": key,
                        "language": language,
                        "path": version["path"],
                        "message": (
                            f"Дата обновления версии «{language}» ({version['updated']}) "
                            f"отличается от «{base_language}» ({base['updated']})"
                        ),
                    }
                )
            if base["version"] and version["version"] and base["version"] != version["version"]:
                article["dates_equal"] = False
                findings.append(
                    {
                        "kind": "version-mismatch",
                        "severity": "warning",
                        "article_id": key,
                        "language": language,
                        "path": version["path"],
                        "message": (
                            f"Версия продукта в «{language}» ({version['version']}) "
                            f"отличается от «{base_language}» ({base['version']})"
                        ),
                    }
                )

        missing = [
            language
            for language in languages.target_languages(config)
            if language not in versions
        ]
        # Рыночно-специфичный контент и просто непереведённые статьи — норма,
        # поэтому отсутствие зеркала сообщается, только если этого требует конфигурация.
        require_all = bool(languages.settings(config).get("require_all_targets", False))
        if missing and require_all and not market_specific:
            findings.append(
                {
                    "kind": "missing-locale",
                    "severity": "warning",
                    "article_id": key,
                    "language": ", ".join(missing),
                    "path": base["path"],
                    "message": f"Нет версий на языках: {', '.join(missing)}",
                }
            )
        article["missing_languages"] = missing
        articles.append(article)

    return {
        "articles": articles,
        "findings": findings,
        "summary": {
            "articles": len(articles),
            "with_findings": len({item["article_id"] for item in findings}),
            "by_kind": {
                kind: sum(1 for item in findings if item["kind"] == kind)
                for kind in sorted({item["kind"] for item in findings})
            },
        },
    }


def as_drift_findings(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Те же расхождения в формате детекта drift — чтобы показывать одним списком."""
    result = compare(config)
    return [
        {
            "kind": item["kind"],
            "severity": item["severity"],
            "doc_path": item["path"],
            "line": 0,
            "message": item["message"],
            "excerpt": item["article_id"],
        }
        for item in result["findings"]
    ]
