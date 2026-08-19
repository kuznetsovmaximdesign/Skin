"""Конфиденциальность, аудит и доступ.

Функциональные требования секретны: внутренний контур (модель, эмбеддинги, индексы)
полностью локален, а всё, что уходит наружу (публикация), проходит через явную проверку
на отсутствие фрагментов ФТ.

В логи пишутся только события — кто, когда, какой документ и какая модель. Ни ФТ,
ни текст документов в логи не попадают.

Доступ: по умолчанию сервис локальный и открыт. Если включён режим Рутокена, каждый
запрос должен нести отпечаток сертификата с аппаратного токена; отпечаток отображается
в роль, а роль ограничивает и продукты, и уровни секретности при поиске.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import resolve_path

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

LEVELS = ("public", "internal", "confidential")
DEFAULT_MARKERS = (
    "функциональные требования",
    "функциональных требований",
    "ФТ:",
    "confidential",
    "коммерческая тайна",
)


def settings(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("security", {}) or {}


def audit_path(config: dict[str, Any]) -> Path:
    return resolve_path(settings(config).get("audit_log", "data/audit.jsonl"))


# --- классификация ----------------------------------------------------------


def front_matter(text: str) -> dict[str, Any]:
    match = FRONT_MATTER_RE.match((text or "").replace("\r\n", "\n"))
    if not match:
        return {}
    loaded = yaml.safe_load(match.group(1)) or {}
    return loaded if isinstance(loaded, dict) else {}


def classify(config: dict[str, Any], text: str = "", doc_path: str = "") -> str:
    """Уровень секретности документа: из front-matter или по правилам путей."""
    declared = str(front_matter(text).get("classification", "")).strip().lower()
    if declared in LEVELS:
        return declared
    for pattern in settings(config).get("confidential_paths", []) or []:
        if doc_path and fnmatch.fnmatch(doc_path, str(pattern)):
            return "confidential"
    return str(settings(config).get("default_classification", "internal")).lower()


def markers(config: dict[str, Any]) -> list[str]:
    configured = settings(config).get("requirement_markers")
    return [str(item) for item in (configured or DEFAULT_MARKERS)]


def contains_requirements(config: dict[str, Any], text: str) -> list[str]:
    """Признаки того, что в тексте есть функциональные требования."""
    found = []
    lowered = (text or "").lower()
    for marker in markers(config):
        if marker.lower() in lowered:
            found.append(marker)
    return found


def check_outbound(config: dict[str, Any], text: str, doc_path: str = "") -> dict[str, Any]:
    """Можно ли выпускать этот текст во внешний контур (публикация)."""
    level = classify(config, text, doc_path)
    found = contains_requirements(config, text)
    allowed = level != "confidential" and not found
    reasons = []
    if level == "confidential":
        reasons.append("документ помечен как конфиденциальный")
    if found:
        reasons.append("в тексте найдены признаки функциональных требований: " + ", ".join(found))
    return {"allowed": allowed, "classification": level, "reasons": reasons}


# --- роли и доступ ----------------------------------------------------------


def roles(config: dict[str, Any]) -> dict[str, Any]:
    return settings(config).get("roles", {}) or {}


def role_for_thumbprint(config: dict[str, Any], thumbprint: str) -> str | None:
    """Отпечаток сертификата с Рутокена → роль."""
    allowed = settings(config).get("tokens", {}) or {}
    for stored, role in allowed.items():
        if str(stored).strip().lower() == (thumbprint or "").strip().lower():
            return str(role)
    return None


def default_role(config: dict[str, Any]) -> str:
    return str(settings(config).get("default_role", "writer"))


def role_settings(config: dict[str, Any], role: str) -> dict[str, Any]:
    return roles(config).get(role, {}) or {}


def allowed_classifications(config: dict[str, Any], role: str) -> set[str]:
    values = role_settings(config, role).get("classifications")
    if not values:
        return {"public", "internal"}
    return {str(item).lower() for item in values}


def allowed_products(config: dict[str, Any], role: str) -> set[str] | None:
    values = role_settings(config, role).get("products")
    return {str(item) for item in values} if values else None


def auth_mode(config: dict[str, Any]) -> str:
    return str(settings(config).get("auth", "none")).lower()


def resolve_role(config: dict[str, Any], thumbprint: str | None) -> tuple[str | None, str]:
    """Возвращает (роль, причина отказа). Роль None — доступ запрещён."""
    if auth_mode(config) != "rutoken":
        return default_role(config), ""
    if not thumbprint:
        return None, (
            "Требуется аппаратный токен: передайте отпечаток сертификата в заголовке "
            "X-Rutoken-Thumbprint."
        )
    role = role_for_thumbprint(config, thumbprint)
    if not role:
        return None, "Сертификат не входит в список разрешённых."
    return role, ""


def may_use_product(config: dict[str, Any], role: str, product: str) -> bool:
    products = allowed_products(config, role)
    return products is None or product in products


def filter_candidates(
    config: dict[str, Any], role: str, candidates: list[dict[str, Any]], read_text
) -> list[dict[str, Any]]:
    """Убирает из выдачи документы, чей уровень секретности роли не положен."""
    permitted = allowed_classifications(config, role)
    result = []
    for candidate in candidates:
        level = classify(config, read_text(candidate["path"]), candidate["path"])
        if level in permitted:
            result.append({**candidate, "classification": level})
    return result


# --- аудит ------------------------------------------------------------------


def fingerprint(value: str) -> str:
    """Короткий отпечаток текста для логов — сам текст в лог не попадает."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


def audit(config: dict[str, Any], event: str, **fields: Any) -> None:
    """Пишет событие в локальный журнал. Содержимое документов и ФТ не логируется."""
    if not settings(config).get("audit", True):
        return
    record = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "product": config.get("product", ""),
    }
    for key, value in fields.items():
        if key in {"text", "content", "requirements", "prompt", "description"}:
            record[f"{key}_fingerprint"] = fingerprint(str(value))
            record[f"{key}_chars"] = len(str(value))
        else:
            record[key] = value

    path = audit_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_audit(config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    path = audit_path(config)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records[-limit:]
