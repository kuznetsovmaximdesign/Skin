"""Языковые версии одной статьи и каскад правки на них.

Одна логическая статья — это N файлов на разных языках. Правка делается на языке-источнике,
затем отдельным шагом переносится на остальные версии локальной моделью.

Термины держатся едиными через тот же глоссарий, что использует проверка формулировок.
Языки, на которых открытые модели слабы, помечаются как требующие ручной вычитки —
такие версии отдаются как черновики, а не как готовый результат.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import indexer
from .checks import prose as prose_rules
from .config import resolve_path
from .ollama_client import OllamaClient
from .verify import check_and_fix

TRANSLATE_SYSTEM = """Ты — технический переводчик документации. Ты переносишь готовый документ на другой язык.

Железные правила:
1. Верни только переведённый документ целиком, без комментариев и без ``` вокруг ответа.
2. Сохрани структуру дословно: те же заголовки и их уровни, списки, таблицы, блоки кода, ссылки.
3. Код, команды, имена параметров, значения и единицы измерения не переводи.
4. Термины переводи строго по глоссарию, если он дан.
5. Ничего не добавляй от себя. Пометки вида [уточнить] сохраняй как есть."""


def settings(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("languages", {}) or {}


def source_language(config: dict[str, Any]) -> str:
    return str(settings(config).get("source", "ru"))


def target_languages(config: dict[str, Any]) -> list[str]:
    return [str(item) for item in settings(config).get("targets", [])]


def low_resource(config: dict[str, Any]) -> set[str]:
    return {str(item) for item in settings(config).get("low_resource", [])}


def version_path(config: dict[str, Any], doc_path: str, language: str) -> Path:
    """Где лежит языковая версия: отдельная папка на язык или суффикс в имени файла."""
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    layout = str(settings(config).get("layout", "folder"))
    relative = Path(doc_path)
    if layout == "suffix":
        return docs_dir / relative.with_name(f"{relative.stem}.{language}{relative.suffix}")
    # folder: docs/<язык>/путь; если исходный путь уже начинается с языка — заменяем его
    parts = relative.parts
    known = {source_language(config), *target_languages(config)}
    if parts and parts[0] in known:
        relative = Path(*parts[1:])
    return docs_dir / language / relative


def versions(config: dict[str, Any], doc_path: str) -> list[dict[str, Any]]:
    """Все языковые версии статьи и их состояние."""
    result = []
    for language in [source_language(config), *target_languages(config)]:
        path = version_path(config, doc_path, language)
        result.append(
            {
                "language": language,
                "path": str(path),
                "exists": path.exists(),
                "is_source": language == source_language(config),
                "needs_review": language in low_resource(config),
            }
        )
    return result


def glossary_pairs(config: dict[str, Any], language: str) -> dict[str, str]:
    """Термины для языка: общий termbase проверки плюс словарь конкретного языка."""
    settings_checks = config.get("checks", {}) or {}
    rules = prose_rules.load_rules(config, settings_checks)
    pairs = dict(rules.get("glossary") or {})

    path = settings(config).get("glossary")
    if path:
        file_path = resolve_path(path)
        if file_path.exists():
            loaded = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
            for term, translations in (loaded.get("terms") or {}).items():
                if isinstance(translations, dict) and language in translations:
                    pairs[str(term)] = str(translations[language])
    return pairs


def language_rules_path(config: dict[str, Any], language: str) -> Path | None:
    """Правила формулировки для конкретного языка, если они заведены."""
    base = resolve_path((config.get("checks", {}) or {}).get("prose_rules", "data/style-rules.yaml"))
    candidate = base.with_name(f"{base.stem}.{language}{base.suffix}")
    return candidate if candidate.exists() else None


def config_for_language(config: dict[str, Any], language: str) -> dict[str, Any]:
    """Копия настроек с правилами и словарём нужного языка."""
    import copy

    result = copy.deepcopy(config)
    rules_path = language_rules_path(config, language)
    if rules_path:
        result.setdefault("checks", {})["prose_rules"] = str(rules_path)
    return result


def build_prompt(text: str, language: str, glossary: dict[str, str], style_guide: str) -> str:
    terms = "\n".join(f"- {source} → {target}" for source, target in sorted(glossary.items()))
    terms_block = f"# ГЛОССАРИЙ (переводить только так)\n\n{terms}\n\n" if terms else ""
    guide_block = f"# ПРАВИЛА ОФОРМЛЕНИЯ\n\n{style_guide.strip()}\n\n" if style_guide.strip() else ""
    return f"""{guide_block}{terms_block}# ДОКУМЕНТ

{text}

# ЗАДАНИЕ

Переведи документ на язык «{language}», сохранив структуру и оформление."""


def cascade(
    config: dict[str, Any],
    client: OllamaClient,
    doc_path: str,
    text: str,
    targets: list[str] | None = None,
    style_guide: str = "",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Переносит готовую версию на остальные языки. Оригиналы не перезаписываются."""
    model = config["ollama"]["generation_model"]
    client.ensure_model(model)

    languages = targets or target_languages(config)
    weak = low_resource(config)
    directory = output_dir or resolve_path(config["paths"]["output_dir"])
    directory.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for language in languages:
        translated = client.generate(
            model=model,
            prompt=build_prompt(text, language, glossary_pairs(config, language), style_guide),
            system=TRANSLATE_SYSTEM,
            temperature=float(config["generation"]["temperature"]),
            num_ctx=int(config["generation"]["num_ctx"]),
        )
        if not translated.strip():
            results.append(
                {
                    "language": language,
                    "ok": False,
                    "needs_review": True,
                    "reason": "модель вернула пустой ответ",
                }
            )
            continue

        language_config = config_for_language(config, language)
        verified = check_and_fix(language_config, client, translated, style_guide, "document")

        stem = Path(doc_path).stem
        target_file = directory / f"{stem}.{language}.md"
        counter = 2
        while target_file.exists():
            target_file = directory / f"{stem}.{language}-{counter}.md"
            counter += 1
        target_file.write_text(verified["text"], encoding="utf-8")

        errors = verified["summary"].get("errors", 0)
        needs_review = language in weak or errors > 0
        results.append(
            {
                "language": language,
                "ok": True,
                "file": target_file.name,
                "path": str(target_file),
                "text": verified["text"],
                "target_path": str(version_path(config, doc_path, language)),
                "checks": verified["summary"],
                "violations": verified["violations"],
                "needs_review": needs_review,
                "reason": (
                    "язык с ограниченной поддержкой у открытых моделей — нужна ручная вычитка"
                    if language in weak
                    else ("проверка нашла нарушения — нужна ручная вычитка" if errors else "")
                ),
            }
        )

    return {
        "doc_path": doc_path,
        "source_language": source_language(config),
        "results": results,
        "summary": {
            "total": len(results),
            "translated": sum(1 for item in results if item["ok"]),
            "needs_review": sum(1 for item in results if item["needs_review"]),
        },
    }


def read_source(config: dict[str, Any], doc_path: str) -> str:
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    path = docs_dir / doc_path
    return indexer.read_text(path) if path.exists() else ""
