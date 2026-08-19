"""Публикация готового документа во внешние площадки.

Единый источник правды — файл сервиса. Из него документ уходит в Confluence и на
справочный портал одновременно, но только по явному подтверждению пользователя.

Внешний контур отделён от внутреннего: перед отправкой каждый документ проходит проверку
на конфиденциальность (backend/security.check_outbound). Функциональные требования наружу
не уходят ни при каких настройках.

Идемпотентность: соответствие «локальный документ ↔ страница Confluence ↔ статья портала»
хранится локально, повторная публикация обновляет ту же страницу, а не создаёт дубликат.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import security
from .config import resolve_path

TIMEOUT = 30


class PublishError(Exception):
    """Понятная ошибка публикации: показывается пользователю как есть."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


def settings(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("publish", {}) or {}


def registry_path(config: dict[str, Any]) -> Path:
    return resolve_path(settings(config).get("registry", "data/publications.json"))


def load_registry(config: dict[str, Any]) -> dict[str, Any]:
    path = registry_path(config)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_registry(config: dict[str, Any], registry: dict[str, Any]) -> None:
    path = registry_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def token_for(target: dict[str, Any]) -> str:
    """Доступ берётся из переменной окружения — в конфиге и в коде секретов нет."""
    name = str(target.get("auth_env", ""))
    return os.environ.get(name, "") if name else ""


def configured_targets(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    published = settings(config)
    result = {}
    for name in ("confluence", "portal"):
        target = published.get(name) or {}
        if target.get("base_url"):
            result[name] = target
    return result


def preview(config: dict[str, Any], doc_path: str, text: str) -> dict[str, Any]:
    """Что и куда уйдёт: площадки, адреса, прошлые публикации, проверка на ФТ."""
    registry = load_registry(config)
    known = registry.get(doc_path, {})
    outbound = security.check_outbound(config, text, doc_path)

    targets = []
    for name, target in configured_targets(config).items():
        previous = known.get(name, {})
        targets.append(
            {
                "target": name,
                "base_url": target.get("base_url", ""),
                "space": target.get("space", ""),
                "existing_id": previous.get("id", ""),
                "action": "обновить" if previous.get("id") else "создать",
                "last_published": previous.get("at", ""),
                "token_ready": bool(token_for(target)),
            }
        )

    return {
        "doc_path": doc_path,
        "enabled": bool(settings(config).get("enabled", False)),
        "targets": targets,
        "outbound": outbound,
        "chars": len(text),
        "preview": text[:2000],
    }


def _confluence_request(target: dict[str, Any], page_id: str, title: str, text: str) -> dict[str, Any]:
    base = str(target["base_url"]).rstrip("/")
    token = token_for(target)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload: dict[str, Any] = {
        "type": "page",
        "title": title,
        "space": {"key": target.get("space", "")},
        "body": {"storage": {"value": text, "representation": "wiki"}},
    }
    if page_id:
        url = f"{base}/rest/api/content/{page_id}"
        payload["version"] = {"number": int(target.get("_next_version", 2))}
        response = httpx.put(url, json=payload, headers=headers, timeout=TIMEOUT)
    else:
        response = httpx.post(f"{base}/rest/api/content", json=payload, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json() if response.content else {}
    return {"id": str(data.get("id", page_id or "")), "version": data.get("version", {}).get("number", 1)}


def _portal_request(target: dict[str, Any], article_id: str, title: str, text: str, doc_path: str) -> dict[str, Any]:
    base = str(target["base_url"]).rstrip("/")
    token = token_for(target)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {"slug": doc_path.replace("/", "-").removesuffix(".md"), "title": title, "content": text}
    if article_id:
        response = httpx.put(f"{base}/api/articles/{article_id}", json=payload, headers=headers, timeout=TIMEOUT)
    else:
        response = httpx.post(f"{base}/api/articles", json=payload, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json() if response.content else {}
    return {"id": str(data.get("id", article_id or "")), "version": data.get("version", 1)}


def publish(
    config: dict[str, Any],
    doc_path: str,
    title: str,
    text: str,
    targets: list[str] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Отправляет документ на площадки. Без подтверждения не отправляет ничего."""
    if not confirmed:
        raise PublishError(
            "Публикация не подтверждена.",
            hint="Посмотрите превью и повторите запрос с confirm: true.",
        )
    if not settings(config).get("enabled", False):
        raise PublishError(
            "Публикация выключена в настройках.",
            hint="Включите publish.enabled и укажите адреса площадок в config.yaml.",
        )

    outbound = security.check_outbound(config, text, doc_path)
    if not outbound["allowed"]:
        raise PublishError(
            "Документ нельзя публиковать: " + "; ".join(outbound["reasons"]),
            hint="Уберите конфиденциальные фрагменты или снимите пометку классификации.",
        )

    available = configured_targets(config)
    wanted = targets or list(available)
    unknown = [name for name in wanted if name not in available]
    if unknown:
        raise PublishError(
            f"Не настроены площадки: {', '.join(unknown)}.",
            hint="Заполните publish.<площадка>.base_url в config.yaml.",
        )

    registry = load_registry(config)
    known = dict(registry.get(doc_path, {}))
    results = []

    for name in wanted:
        target = dict(available[name])
        previous = known.get(name, {})
        try:
            if name == "confluence":
                target["_next_version"] = int(previous.get("version", 1)) + 1
                outcome = _confluence_request(target, previous.get("id", ""), title, text)
            else:
                outcome = _portal_request(target, previous.get("id", ""), title, text, doc_path)
        except httpx.HTTPError as exc:
            results.append({"target": name, "ok": False, "error": str(exc)})
            continue

        known[name] = {
            "id": outcome["id"],
            "version": outcome["version"],
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        results.append(
            {
                "target": name,
                "ok": True,
                "id": outcome["id"],
                "version": outcome["version"],
                "action": "обновлено" if previous.get("id") else "создано",
            }
        )

    registry[doc_path] = known
    save_registry(config, registry)

    return {
        "doc_path": doc_path,
        "results": results,
        "registry": known,
        "summary": {
            "published": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
        },
    }
