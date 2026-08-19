"""Проверка формулировок: запрещённые слова, замены, длина предложений, пассив, глоссарий.

Это встроенный аналог правил Vale — работает всегда, даже если бинарник Vale не установлен.
Правила лежат в отдельном YAML, чтобы их правил редактор, а не программист.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from ..config import resolve_path

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
PASSIVE_RE = re.compile(r"\b\w+(?:ется|ются|ался|алась|ались|ано|ена|ено|ены)\b", re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

_cache: dict[str, Any] = {}


def load_rules(config: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(settings.get("prose_rules", "data/style-rules.yaml"))
    if not path.exists():
        return {}
    key = f"{path}:{path.stat().st_mtime}"
    if key not in _cache:
        _cache.clear()
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _cache[key] = loaded if isinstance(loaded, dict) else {}
    return _cache[key]


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Строки прозы: без блоков кода, таблиц и заголовков."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    result: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(("|", ">")):
            continue
        result.append((number, line))
    return result


def check(text: str, settings: dict[str, Any], config: dict[str, Any]) -> list[Any]:
    from . import Violation

    rules = load_rules(config, settings)
    violations: list[Violation] = []

    forbidden: dict[str, str] = rules.get("forbidden", {}) or {}
    substitutions: dict[str, str] = rules.get("substitutions", {}) or {}
    glossary: dict[str, str] = rules.get("glossary", {}) or {}
    max_words = int(rules.get("max_sentence_words", settings.get("max_sentence_words", 25)))
    forbid_passive = bool(rules.get("check_passive", True))

    for number, line in prose_lines(text):
        clean = INLINE_CODE_RE.sub(" ", line)

        for word, reason in forbidden.items():
            if re.search(rf"\b{re.escape(word)}\b", clean, re.IGNORECASE):
                violations.append(
                    Violation("prose", "forbidden", "error", number, f"Слово «{word}» использовать нельзя: {reason}", word)
                )

        for wrong, right in {**substitutions, **glossary}.items():
            if re.search(rf"\b{re.escape(wrong)}\b", clean, re.IGNORECASE):
                violations.append(
                    Violation("prose", "substitution", "error", number, f"Вместо «{wrong}» пишем «{right}»", wrong)
                )

        for sentence in SENTENCE_SPLIT_RE.split(clean.strip()):
            words = [word for word in sentence.split() if word.strip()]
            if len(words) > max_words:
                violations.append(
                    Violation(
                        "prose",
                        "sentence-length",
                        "warning",
                        number,
                        f"Предложение из {len(words)} слов, по правилам — не больше {max_words}",
                        " ".join(words[:6]) + "…",
                    )
                )
            if forbid_passive and len(words) > 3:
                passive = PASSIVE_RE.search(sentence)
                if passive:
                    violations.append(
                        Violation(
                            "prose",
                            "passive-voice",
                            "warning",
                            number,
                            "Похоже на пассивный залог — перепишите активным",
                            passive.group(0),
                        )
                    )
    return violations
