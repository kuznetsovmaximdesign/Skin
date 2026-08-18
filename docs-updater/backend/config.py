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
        "generation_model": "qwen3",
        "embedding_model": "bge-m3",
        "request_timeout": 900,
    },
    "paths": {
        "docs_dir": "data/docs",
        "style_guide": "data/styleguide.md",
        "index_file": "data/index.json",
        "output_dir": "data/output",
    },
    "search": {"top_k": 5, "chunk_max_chars": 1800},
    "generation": {"temperature": 0.2, "num_ctx": 16384},
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


def resolve_path(value: str | Path) -> Path:
    """Относительные пути считаются от корня docs-updater/, абсолютные — как есть."""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
