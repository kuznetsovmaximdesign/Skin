"""Глоссарий из docs-config → словарь Vale и правила замен.

Термбанк один: его используют и проверка формулировок, и перевод языковых версий.
Отсюда собираются три вещи:

- accept.txt — принятые написания (Vale не считает их ошибками);
- reject.txt — написания, которых быть не должно;
- Corp/GlossarySubstitutions.yml — замены «избегать X → использовать Y».

Учтены два наблюдения разбора: эквивалент термина в другой локали может быть
небуквальным (это не ошибка перевода), а часть терминов существует только в одной
локали (регуляторные) и не обязана иметь зеркало во всех языках.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import docs_config
from .config import resolve_path

VOCAB_DIR = "styles/config/vocabularies/Corp"
STYLE_DIR = "styles/Corp"


def vocabulary_dir(config: dict[str, Any]) -> Path:
    return resolve_path((config.get("checks", {}) or {}).get("vale_vocabulary_dir", VOCAB_DIR))


def style_dir(config: dict[str, Any]) -> Path:
    return resolve_path((config.get("checks", {}) or {}).get("vale_style_dir", STYLE_DIR))


def sync(config: dict[str, Any]) -> dict[str, Any]:
    """Пересобирает словари Vale из glossary.csv. Возвращает, что записано."""
    data = docs_config.glossary(config)
    if data.get("error"):
        return {"ok": False, "error": data["error"], "written": []}

    vocab = vocabulary_dir(config)
    styles = style_dir(config)
    vocab.mkdir(parents=True, exist_ok=True)
    styles.mkdir(parents=True, exist_ok=True)

    accept = sorted({term for term in data["accepted"] if term})
    reject = sorted({wrong for wrong in data["substitutions"] if wrong})
    written: list[str] = []

    accept_path = vocab / "accept.txt"
    accept_path.write_text("\n".join(accept) + ("\n" if accept else ""), encoding="utf-8")
    written.append(str(accept_path))

    reject_path = vocab / "reject.txt"
    reject_path.write_text("\n".join(reject) + ("\n" if reject else ""), encoding="utf-8")
    written.append(str(reject_path))

    substitutions_path = styles / "GlossarySubstitutions.yml"
    substitutions_path.write_text(
        yaml.safe_dump(
            {
                "extends": "substitution",
                "message": "Вместо «%s» пишем «%s» (глоссарий).",
                "level": "error",
                "ignorecase": True,
                "swap": data["substitutions"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    written.append(str(substitutions_path))

    return {
        "ok": True,
        "written": written,
        "accepted": len(accept),
        "rejected": len(reject),
        "do_not_translate": data["keep"],
    }


def translation_pairs(config: dict[str, Any], language: str) -> dict[str, str]:
    """Пары «термин → эквивалент» для перевода, без терминов «не переводить»."""
    pairs: dict[str, str] = {}
    for entry in docs_config.glossary(config)["terms"]:
        if entry["do_not_translate"]:
            continue
        translation = (entry.get("translation") or "").strip()
        if translation:
            pairs[entry["accepted"]] = translation
    return pairs


def keep_as_is(config: dict[str, Any]) -> list[str]:
    """Продуктовые и сервисные имена, которые остаются как есть во всех локалях."""
    return docs_config.glossary(config)["keep"]
