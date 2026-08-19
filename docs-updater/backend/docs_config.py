"""Чтение артефактов разбора портала из docs-config/ — единственного источника правды.

Правила задаются файлами, а не кодом: изменили файл — изменились правила. Файлы
перечитываются автоматически, когда меняется время их изменения.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from .config import resolve_path

DEFAULT_DIR = "docs-config"
FILES = {
    "schemas": "article-type-schemas.json",
    "rules": "markdownlint-rule-candidates.md",
    "glossary": "glossary.csv",
    "report": "report.md",
}

JSON_BLOCK_RE = re.compile(r"```(?:jsonc?|json5)\s*\n(.*?)```", re.DOTALL)
KDOC_RE = re.compile(r"`?(KDOC-[A-Z0-9-]+)`?")
COMMENT_RE = re.compile(r"(?<!:)//.*?$", re.MULTILINE)

WARNING_WORDS = ("рекоменд", "warning", "предупрежд", "открытый вопрос", "спорн")
ERROR_WORDS = ("ошибка", "error", "обязательн", "нарушение")
OFF_WORDS = ("выключено", "отключено", "off", "disabled")

_cache: dict[str, Any] = {}


def config_dir(config: dict[str, Any]) -> Path:
    """Папка с артефактами разбора.

    По умолчанию берётся `docs-config/` в корне репозитория (рядом с папкой сервиса),
    а если её нет — одноимённая папка внутри сервиса. Путь можно задать явно
    в config.yaml: checks.docs_config_dir.
    """
    configured = (config.get("checks", {}) or {}).get("docs_config_dir")
    if configured:
        return resolve_path(configured)
    repo_level = resolve_path(f"../{DEFAULT_DIR}")
    return repo_level if repo_level.exists() else resolve_path(DEFAULT_DIR)


def file_path(config: dict[str, Any], key: str) -> Path:
    return config_dir(config) / FILES[key]


def _stamp(config: dict[str, Any]) -> str:
    parts = []
    for key in FILES:
        path = file_path(config, key)
        parts.append(f"{path}:{path.stat().st_mtime if path.exists() else 0}")
    return "|".join(parts)


def load(config: dict[str, Any]) -> dict[str, Any]:
    """Все артефакты разом, с кэшем по времени изменения файлов."""
    stamp = _stamp(config)
    if _cache.get("stamp") != stamp:
        _cache.clear()
        _cache["stamp"] = stamp
        schemas = load_schemas(config)
        _cache["data"] = {
            "dir": str(config_dir(config)),
            "schemas": schemas,
            "rules": load_rules(
                config,
                [entry["type_id"] for entry in schemas["types"]],
                schemas["profiles"],
            ),
            "glossary": load_glossary(config),
            "report_present": file_path(config, "report").exists(),
        }
    return _cache["data"]


# --- типы статей ------------------------------------------------------------


def load_schemas(config: dict[str, Any]) -> dict[str, Any]:
    path = file_path(config, "schemas")
    if not path.exists():
        return {"types": [], "profiles": [], "admonition_types": [], "error": f"нет файла {path.name}"}
    try:
        raw = json.loads(COMMENT_RE.sub("", path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        return {"types": [], "profiles": [], "admonition_types": [], "error": f"{path.name}: {error}"}

    types = raw.get("types")
    if isinstance(types, dict):  # допускаем словарь, ключ — type_id
        types = [{**value, "type_id": key} for key, value in types.items()]
    if not isinstance(types, list):
        types = []

    normalized = []
    for entry in types:
        if not isinstance(entry, dict) or not entry.get("type_id"):
            continue
        normalized.append(
            {
                "type_id": str(entry["type_id"]),
                "name": str(entry.get("name", entry["type_id"])),
                "profiles": [str(item) for item in entry.get("profiles", [])],
                "required_sections": [str(item) for item in entry.get("required_sections", [])],
                "optional_sections": [str(item) for item in entry.get("optional_sections", [])],
                "enforce_order": bool(entry.get("enforce_order", True)),
                "section_levels": {str(k): int(v) for k, v in (entry.get("section_levels") or {}).items()},
                "required_meta": normalize_meta(entry.get("required_meta")),
                "detect": entry.get("detect") or {},
                "rules": {str(k): str(v) for k, v in (entry.get("rules") or {}).items()},
                "lintable": bool(entry.get("lintable", True)),
                "market_specific": bool(entry.get("market_specific", False)),
                "note": str(entry.get("note", "")),
            }
        )

    return {
        "types": normalized,
        "profiles": [str(item) for item in raw.get("profiles", [])] or ["legacy_help", "modern_help", "modern_kb"],
        "admonition_types": [str(item).lower() for item in raw.get("admonition_types", [])]
        or ["note", "warning", "important", "example"],
        "error": "",
    }


def normalize_meta(value: Any) -> dict[str, list[str]]:
    """Обязательные метаполя: общий список или словарь «профиль → поля»."""
    if isinstance(value, list):
        return {"*": [str(item) for item in value]}
    if isinstance(value, dict):
        return {str(key): [str(item) for item in items or []] for key, items in value.items()}
    return {}


def types(config: dict[str, Any]) -> list[dict[str, Any]]:
    return load(config)["schemas"]["types"]


def type_by_id(config: dict[str, Any], type_id: str) -> dict[str, Any] | None:
    return next((entry for entry in types(config) if entry["type_id"] == type_id), None)


def profiles(config: dict[str, Any]) -> list[str]:
    return load(config)["schemas"]["profiles"]


def admonition_types(config: dict[str, Any]) -> list[str]:
    return load(config)["schemas"]["admonition_types"]


def required_meta_for(entry: dict[str, Any], profile: str) -> list[str]:
    meta = entry.get("required_meta") or {}
    return list(meta.get(profile) or meta.get("*") or [])


# --- правила ----------------------------------------------------------------


def load_rules(
    config: dict[str, Any],
    known_types: list[str] | None = None,
    known_profiles: list[str] | None = None,
) -> dict[str, Any]:
    """Стандартные коды markdownlint и список кастомных KDOC-правил с уровнями.

    Привязки в строке правила пишутся в обратных кавычках. Их нужно различать:
    `troubleshooting` — тип статьи, `modern_help` — профиль шаблона.
    """
    known_types = known_types or []
    known_profiles = known_profiles or []
    path = file_path(config, "rules")
    if not path.exists():
        return {"markdownlint": {}, "kdoc": {}, "error": f"нет файла {path.name}"}

    text = path.read_text(encoding="utf-8")
    markdownlint: dict[str, Any] = {}
    block = JSON_BLOCK_RE.search(text)
    if block:
        try:
            markdownlint = json.loads(COMMENT_RE.sub("", block.group(1)))
        except json.JSONDecodeError:
            markdownlint = {}

    kdoc: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        found = KDOC_RE.search(line)
        if not found:
            continue
        rule_id = found.group(1)
        lowered = line.lower()
        if any(word in lowered for word in OFF_WORDS):
            severity, enabled = "warning", False
        elif any(word in lowered for word in WARNING_WORDS):
            severity, enabled = "warning", True
        elif any(word in lowered for word in ERROR_WORDS):
            severity, enabled = "error", True
        else:
            severity, enabled = "warning", True

        mentioned = re.findall(r"`([a-z_]+)`", line)
        bound_types = [item for item in mentioned if item in known_types]
        bound_profiles = [item for item in mentioned if item in known_profiles]

        kdoc[rule_id] = {
            "id": rule_id,
            "severity": severity,
            "enabled": enabled,
            "types": bound_types,
            "profiles": bound_profiles,
            "description": line.strip(" -*"),
        }
    return {"markdownlint": markdownlint, "kdoc": kdoc, "error": ""}


def kdoc_rules(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Правила KDOC с учётом переопределений из config.yaml (checks.kdoc)."""
    rules = dict(load(config)["rules"]["kdoc"])
    overrides = (config.get("checks", {}) or {}).get("kdoc", {}) or {}
    for rule_id, override in overrides.items():
        entry = dict(
            rules.get(rule_id) or {"id": rule_id, "types": [], "profiles": [], "description": ""}
        )
        if isinstance(override, str):
            if override.lower() in {"off", "выключено"}:
                entry["enabled"] = False
            else:
                entry["severity"] = override
                entry["enabled"] = True
        elif isinstance(override, dict):
            entry.update(override)
        rules[rule_id] = entry
    return rules


def markdownlint_config(config: dict[str, Any]) -> dict[str, Any]:
    return load(config)["rules"]["markdownlint"]


# --- глоссарий --------------------------------------------------------------

HEADER_MAP = {
    "term": "term", "термин": "term",
    "accepted": "accepted", "принятое написание": "accepted", "принятое": "accepted",
    "avoid": "avoid", "избегать": "avoid", "не использовать": "avoid",
    "translation": "translation", "перевод": "translation",
    "do_not_translate": "keep", "не переводить": "keep",
    "locale": "locale", "локаль": "locale",
    "notes": "notes", "комментарий": "notes",
}
YES = {"да", "yes", "true", "1", "y", "+"}


def load_glossary(config: dict[str, Any]) -> dict[str, Any]:
    """Термбанк: принятые написания, замены, «не переводить», эквиваленты локалей."""
    path = file_path(config, "glossary")
    if not path.exists():
        return {"terms": [], "accepted": [], "substitutions": {}, "keep": [], "error": f"нет файла {path.name}"}

    text = path.read_text(encoding="utf-8-sig")
    sample = text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    terms: list[dict[str, Any]] = []
    accepted: list[str] = []
    substitutions: dict[str, str] = {}
    keep: list[str] = []

    for row in reader:
        mapped: dict[str, str] = {}
        for key, value in row.items():
            if key is None:
                continue
            name = HEADER_MAP.get(key.strip().lower())
            if name:
                mapped[name] = (value or "").strip()

        term = mapped.get("term") or ""
        if not term:
            continue
        proper = mapped.get("accepted") or term
        avoid = [item.strip() for item in re.split(r"[;|]", mapped.get("avoid", "")) if item.strip()]
        do_not_translate = (mapped.get("keep", "").lower() in YES)

        accepted.append(proper)
        for wrong in avoid:
            substitutions[wrong] = proper
        if do_not_translate:
            keep.append(proper)

        terms.append(
            {
                "term": term,
                "accepted": proper,
                "avoid": avoid,
                "translation": mapped.get("translation", ""),
                "do_not_translate": do_not_translate,
                "locale": mapped.get("locale", ""),
                "notes": mapped.get("notes", ""),
            }
        )

    return {
        "terms": terms,
        "accepted": sorted(set(accepted)),
        "substitutions": substitutions,
        "keep": sorted(set(keep)),
        "error": "",
    }


def glossary(config: dict[str, Any]) -> dict[str, Any]:
    return load(config)["glossary"]


def summary(config: dict[str, Any]) -> dict[str, Any]:
    """Что сейчас загружено — для интерфейса и диагностики."""
    data = load(config)
    schemas, rules, terms = data["schemas"], data["rules"], data["glossary"]
    return {
        "dir": data["dir"],
        "files": {
            key: {
                "name": FILES[key],
                "present": file_path(config, key).exists(),
                "path": str(file_path(config, key)),
            }
            for key in FILES
        },
        "types": [
            {
                "type_id": entry["type_id"],
                "name": entry["name"],
                "profiles": entry["profiles"],
                "lintable": entry["lintable"],
                "required_sections": entry["required_sections"],
            }
            for entry in schemas["types"]
        ],
        "profiles": schemas["profiles"],
        "admonition_types": schemas["admonition_types"],
        "kdoc": sorted(kdoc_rules(config).values(), key=lambda item: item["id"]),
        "markdownlint_codes": sorted(rules["markdownlint"].keys()),
        "glossary": {
            "terms": len(terms["terms"]),
            "substitutions": len(terms["substitutions"]),
            "do_not_translate": terms["keep"],
        },
        "errors": [item for item in (schemas.get("error"), rules.get("error"), terms.get("error")) if item],
    }
