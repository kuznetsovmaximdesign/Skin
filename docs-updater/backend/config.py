"""Чтение и запись config.yaml. Все относительные пути разрешаются от корня проекта."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Можно указать другой конфиг: DOCS_UPDATER_CONFIG=/путь/config.yaml uvicorn backend.main:app
CONFIG_PATH = Path(os.environ.get("DOCS_UPDATER_CONFIG") or PROJECT_ROOT / "config.yaml")

DEFAULTS: dict[str, Any] = {
    "ollama": {
        "host": "http://localhost:11434",
        "generation_model": "qwen3:4b",
        "embedding_model": "bge-m3",
        "keep_alive": "5m",
        "sequential_models": True,
        "request_timeout": 900,
    },
    "paths": {
        "docs_dir": "data/docs",
        # Файлы с правилами оформления. Можно несколько — все попадут в инструкцию модели.
        "style_guides": ["data/styleguide.md"],
        # Старое поле на один файл: поддерживается для совместимости.
        "style_guide": "data/styleguide.md",
        # Папка с образцами: по ним сервис сам выводит формат.
        "samples_dir": "data/samples",
        # Куда сохраняются выведенные из образцов правила.
        "derived_guide": "data/derived-guide.md",
        # Учитывать ли выведенные правила при генерации.
        "use_derived_guide": True,
        "index_file": "data/index.sqlite3",
        "output_dir": "data/output",
        "changesets_dir": "data/changesets",
        "feedback_log": "data/feedback.jsonl",
    },
    "search": {"top_k": 5, "chunk_max_chars": 1800, "embed_batch": 8},
    "generation": {"temperature": 0.2, "num_ctx": 8192},
    # Продукты: у каждого свои документы, гайды, шаблон и индекс.
    # Незаданные поля продукт наследует из общих настроек выше.
    "products": {
        "default": "core",
        "items": {
            "core": {"name": "Основной продукт"},
        },
    },
    "languages": {
        "source": "ru",
        "targets": [],
        "layout": "folder",
        "low_resource": [],
        "glossary": "data/glossary.yaml",
    },
    "publish": {
        "enabled": False,
        "confluence": {"base_url": "", "space": "", "auth_env": "CONFLUENCE_TOKEN"},
        "portal": {"base_url": "", "auth_env": "PORTAL_TOKEN"},
        "registry": "data/publications.json",
    },
    "security": {
        "auth": "none",
        "tokens": {},
        "default_role": "writer",
        "roles": {
            "writer": {"classifications": ["public", "internal"]},
            "lead": {"classifications": ["public", "internal", "confidential"]},
        },
        "confidential_paths": ["secret/*", "*/secret/*"],
        "default_classification": "internal",
        "audit": True,
        "audit_log": "data/audit.jsonl",
    },
    "checks": {
        "enabled": True,
        "builtin_prose": True,
        "builtin_markdown": True,
        "schema": True,
        "prose_rules": "data/style-rules.yaml",
        "template_schema": "data/template.schema.yaml",
        "max_line_length": 120,
        "bullet_marker": "-",
        "require_fence_language": True,
        "use_vale": True,
        "vale_binary": "vale",
        "vale_config": ".vale.ini",
        "use_markdownlint": True,
        "markdownlint_command": "markdownlint-cli2",
        "max_fix_iterations": 2,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    return _merge(DEFAULTS, raw)


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def product_ids(config: dict[str, Any]) -> list[str]:
    items = (config.get("products") or {}).get("items") or {}
    return list(items.keys())


def default_product(config: dict[str, Any]) -> str:
    products = config.get("products") or {}
    items = products.get("items") or {}
    wanted = products.get("default")
    if wanted in items:
        return wanted
    return next(iter(items), "core")


def for_product(config: dict[str, Any], product: str | None = None) -> dict[str, Any]:
    """Настройки одного продукта: общие правила плюс его собственные переопределения.

    Изоляция контекстов делается здесь: дальше весь код работает с путями продукта
    и физически не видит документы и гайды соседнего.
    """
    products = config.get("products") or {}
    items = products.get("items") or {}
    chosen = product or default_product(config)
    if chosen not in items:
        raise KeyError(chosen)

    entry = dict(items[chosen] or {})
    result = copy.deepcopy(config)
    result["product"] = chosen
    result["product_name"] = entry.get("name", chosen)

    for section in ("paths", "checks", "ollama", "search", "generation"):
        override = entry.get(section)
        if isinstance(override, dict):
            result[section] = _merge(result.get(section, {}), override)

    # Короткая форма: поля путей можно писать прямо в продукте, без вложенного paths.
    path_keys = set(DEFAULTS["paths"]) | {"rules_dir"}
    inline_paths = {key: value for key, value in entry.items() if key in path_keys}
    if inline_paths:
        result["paths"] = _merge(result["paths"], inline_paths)

    check_keys = set(DEFAULTS["checks"])
    inline_checks = {key: value for key, value in entry.items() if key in check_keys}
    if inline_checks:
        result["checks"] = _merge(result["checks"], inline_checks)
    return result


def style_guide_paths(config: dict[str, Any]) -> list[Path]:
    """Все файлы правил оформления: новое поле style_guides плюс старое style_guide."""
    raw = config["paths"].get("style_guides") or []
    if isinstance(raw, str):
        raw = [raw]
    single = config["paths"].get("style_guide")
    if single and single not in raw:
        raw = [single, *raw]
    seen: list[Path] = []
    for item in raw:
        path = resolve_path(item)
        if path not in seen:
            seen.append(path)
    return seen


def resolve_path(value: str | Path) -> Path:
    """Относительные пути считаются от корня docs-updater/, абсолютные — как есть."""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
