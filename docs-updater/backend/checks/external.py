"""Запуск внешних офлайн-линтеров: Vale и markdownlint-cli2.

Оба необязательны. Если бинарника нет — молча пропускаем: встроенные правила
уже покрывают ту же территорию. Никаких сетевых обращений: только локальные процессы.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, resolve_path

TIMEOUT = 60


def _write_temp(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


def available(command: str) -> str | None:
    return shutil.which(command)


def run_vale(text: str, settings: dict[str, Any], config: dict[str, Any]) -> list[Any]:
    from . import Violation

    if not settings.get("use_vale", True):
        return []
    binary = available(str(settings.get("vale_binary", "vale")))
    if not binary:
        return []

    vale_config = resolve_path(settings.get("vale_config", ".vale.ini"))
    path = _write_temp(text)
    try:
        command = [binary, "--output=JSON", "--no-exit"]
        if vale_config.exists():
            command.append(f"--config={vale_config}")
        result = subprocess.run(
            command + [str(path)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=PROJECT_ROOT,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    finally:
        path.unlink(missing_ok=True)

    violations = []
    for issues in payload.values():
        for issue in issues:
            violations.append(
                Violation(
                    "vale",
                    str(issue.get("Check", "vale")),
                    "error" if str(issue.get("Severity")) == "error" else "warning",
                    int(issue.get("Line", 0)),
                    str(issue.get("Message", "")),
                    str(issue.get("Match", "")),
                )
            )
    return violations


def run_markdownlint(text: str, settings: dict[str, Any], config: dict[str, Any]) -> list[Any]:
    from . import Violation

    if not settings.get("use_markdownlint", True):
        return []
    command_name = str(settings.get("markdownlint_command", "markdownlint-cli2"))
    binary = available(command_name)
    if not binary:
        return []

    path = _write_temp(text)
    try:
        result = subprocess.run(
            [binary, "--json", str(path)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=PROJECT_ROOT,
        )
        payload = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    finally:
        path.unlink(missing_ok=True)

    violations = []
    for issue in payload if isinstance(payload, list) else []:
        names = issue.get("ruleNames") or ["markdownlint"]
        violations.append(
            Violation(
                "markdownlint",
                "/".join(str(name) for name in names[:2]),
                "warning",
                int(issue.get("lineNumber", 0)),
                str(issue.get("ruleDescription", "")) + (f": {issue.get('errorDetail')}" if issue.get("errorDetail") else ""),
                str(issue.get("errorContext") or ""),
            )
        )
    return violations
