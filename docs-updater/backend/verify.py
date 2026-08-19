"""Цикл «сгенерировал → проверил → починил» — общий для всех сценариев.

Его вызывают и правка существующего документа, и генерация новой статьи:
второй копии проверки в проекте нет.
"""

from __future__ import annotations

from typing import Any

from . import checks, generator
from .ollama_client import OllamaClient


def check_and_fix(
    config: dict[str, Any],
    client: OllamaClient,
    text: str,
    style_guide: str,
    scope: str,
) -> dict[str, Any]:
    """Проверяет текст и просит модель починить нарушения. Не больше нескольких заходов.

    Всё, что осталось после починки, возвращается писателю как предупреждения —
    ничего не прячем.
    """
    settings = checks.checks_config(config)
    violations = checks.run_checks(text, config, scope=scope)
    iterations = 0
    max_iterations = int(settings.get("max_fix_iterations", 2)) if settings.get("enabled", True) else 0

    while violations and iterations < max_iterations:
        errors = [item for item in violations if item.severity == "error"]
        target = errors or violations
        repaired = generator.fix_violations(
            config, client, text, checks.as_instruction(target), style_guide
        )
        iterations += 1
        if not repaired.strip():
            break
        candidate = checks.run_checks(repaired, config, scope=scope)
        # Принимаем починку, только если нарушений стало меньше.
        if len(candidate) >= len(violations):
            break
        text, violations = repaired, candidate

    return {
        "text": text,
        "violations": [item.as_dict() for item in violations],
        "summary": checks.summarize(violations),
        "iterations": iterations,
    }


