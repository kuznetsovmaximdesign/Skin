"""Профили шаблона документа: legacy_help, modern_help, modern_kb.

Портал не единообразен — поколения шаблона сосуществуют, и формат метаданных у Online Help
и Knowledge Base разный. Профиль определяет, какие правила и какой формат метаданных
применять; правила одного профиля к другому не применяются.

Профиль берётся из front-matter документа, иначе определяется эвристикой.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FOOTER_META_RE = re.compile(
    r"(идентификатор статьи|article[ _-]?id|дата обновления|last[ _-]?updated)", re.IGNORECASE
)
KB_HINTS = ("kb_id", "kb-id", "knowledge base", "база знаний", "статья базы знаний")

DEFAULT_PROFILES = ("legacy_help", "modern_help", "modern_kb")
PROFILE_KEYS = ("template_profile", "profile", "шаблон", "профиль")


def front_matter(text: str) -> dict[str, Any]:
    match = FRONT_MATTER_RE.match((text or "").replace("\r\n", "\n"))
    if not match:
        return {}
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def declared_profile(text: str) -> str:
    meta = front_matter(text)
    for key in PROFILE_KEYS:
        value = meta.get(key)
        if value:
            return str(value).strip().lower()
    return ""


def detect_profile(text: str, known: list[str] | None = None) -> dict[str, Any]:
    """Профиль документа и то, откуда он взялся."""
    available = [item.lower() for item in (known or DEFAULT_PROFILES)]

    declared = declared_profile(text)
    if declared:
        return {
            "profile": declared,
            "source": "front-matter",
            "known": declared in available,
        }

    meta = front_matter(text)
    lowered = (text or "").lower()

    # Knowledge Base: у статей свой идентификатор и своё оформление метаданных.
    if any(key in meta for key in ("kb_id", "kb-id")) or any(hint in lowered for hint in KB_HINTS):
        return {"profile": "modern_kb", "source": "эвристика: признаки базы знаний", "known": True}

    # Новое поколение Online Help: есть машиночитаемый front-matter.
    if meta:
        return {"profile": "modern_help", "source": "эвристика: есть front-matter", "known": True}

    # Старое поколение: метаданные только текстом в подвале статьи или их нет вовсе.
    if FOOTER_META_RE.search(text or ""):
        return {"profile": "legacy_help", "source": "эвристика: метаданные в подвале", "known": True}

    return {"profile": available[0] if available else "legacy_help", "source": "по умолчанию", "known": True}


# Как называются метаполя в подвале статьи старого поколения.
FOOTER_KEYS = {
    "идентификатор статьи": "article_id",
    "article id": "article_id",
    "article_id": "article_id",
    "продукт": "product",
    "product": "product",
    "версия": "version",
    "version": "version",
    "дата обновления": "updated",
    "last updated": "updated",
    "updated": "updated",
    "локаль": "locale",
    "язык": "locale",
    "locale": "locale",
}
FOOTER_PAIR_RE = re.compile(
    r"(?:^|[.;,]\s+|\*\s*)([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё _-]{2,29})\s*[:：]\s*"
    r"([^.;*]+?)(?=(?:[.;]\s+[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё _-]{2,29}\s*[:：])|[.;*]?\s*$)"
)


def meta_fields(text: str) -> dict[str, Any]:
    """Метаполя документа: из front-matter, а для старого профиля — из подвала статьи.

    В подвале несколько полей часто идут одной строкой: «Идентификатор статьи: X.
    Продукт: Y. Дата обновления: Z» — разбираем такую строку по парам «поле: значение».
    """
    meta = dict(front_matter(text))
    if meta:
        return meta

    footer: dict[str, Any] = {}
    for line in (text or "").splitlines():
        if not FOOTER_META_RE.search(line):
            continue
        for raw_key, raw_value in FOOTER_PAIR_RE.findall(line.strip(" *_")):
            key = FOOTER_KEYS.get(raw_key.strip().lower())
            if key and raw_value.strip():
                footer.setdefault(key, raw_value.strip())
    return footer
