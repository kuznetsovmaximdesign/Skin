"""Проверка готовности сервиса: что уже настроено, а что нет.

Запуск из папки docs-updater:

    python3 check.py

Скрипт ничего не меняет. Он только смотрит и пишет, что делать дальше.
Единственное сетевое обращение — к Ollama на localhost.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK, FAIL, WARN = "  ✓", "  ✗", "  •"


def say(mark: str, title: str, hint: str = "") -> bool:
    print(f"{mark} {title}")
    if hint:
        print(f"      {hint}")
    return mark == OK


def check_python() -> bool:
    version = sys.version_info
    if version >= (3, 10):
        return say(OK, f"Python {version.major}.{version.minor}")
    return say(FAIL, f"Python {version.major}.{version.minor} — нужен 3.10 или новее",
               "Обновите Python с python.org и создайте окружение заново.")


def check_packages() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import httpx  # noqa: F401
        import yaml  # noqa: F401
    except ImportError as error:
        return say(FAIL, f"Не установлены зависимости ({error.name})",
                   "source .venv/bin/activate && pip install -r requirements.txt")
    return say(OK, "Зависимости Python установлены")


def check_ollama_app() -> bool:
    if shutil.which("ollama"):
        return say(OK, "Программа Ollama установлена")
    return say(FAIL, "Программа Ollama не найдена",
               "Скачайте её с ollama.com, откройте один раз и перезапустите терминал.")


def ollama_models(host: str = "http://localhost:11434") -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return [str(item.get("name", "")) for item in data.get("models", [])]


def check_ollama_running(models: list[str] | None) -> bool:
    if models is None:
        return say(FAIL, "Ollama не отвечает на localhost:11434",
                   "Откройте программу Ollama или выполните в другом окне: ollama serve")
    return say(OK, "Ollama отвечает")


def config_models() -> tuple[str, str]:
    try:
        import yaml
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return "qwen3:4b", "bge-m3"
    ollama = config.get("ollama", {}) or {}
    return str(ollama.get("generation_model", "qwen3:4b")), str(ollama.get("embedding_model", "bge-m3"))


def check_models(installed: list[str] | None) -> bool:
    generation, embedding = config_models()
    if installed is None:
        return say(WARN, "Модели проверить не удалось: Ollama не отвечает")
    missing = [
        name for name in (generation, embedding)
        if not any(item == name or item.split(":")[0] == name.split(":")[0] for item in installed)
    ]
    if missing:
        return say(FAIL, f"Не скачаны модели: {', '.join(missing)}",
                   "  ".join(f"ollama pull {name}" for name in missing))
    return say(OK, f"Модели на месте: {generation}, {embedding}")


def check_design_system() -> bool:
    needed = ["_ds_bundle.js", "_ds_bundle.css", "styles.css", "fonts/fonts.css"]
    folder = ROOT / "frontend" / "vendor" / "hexa"
    missing = [name for name in needed if not (folder / name).exists()]
    if missing:
        return say(FAIL, "Не установлена дизайн-система HEXA",
                   "python3 install_ui.py путь/до/выгрузки-дизайна.zip")
    return say(OK, "Дизайн-система на месте")


def check_docs() -> bool:
    try:
        import yaml
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return say(WARN, "Не удалось прочитать config.yaml")
    raw = str((config.get("paths", {}) or {}).get("docs_dir", "data/docs"))
    folder = Path(raw) if Path(raw).is_absolute() else ROOT / raw
    if not folder.exists():
        return say(FAIL, f"Папка с документами не найдена: {folder}",
                   "Укажите свою папку на экране «Настройки и документы» или в config.yaml.")
    count = len(list(folder.rglob("*.md")))
    if count == 0:
        return say(WARN, f"В папке {folder} нет файлов .md")
    return say(OK, f"Документов .md в папке: {count}")


def check_index() -> bool:
    try:
        import yaml
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    raw = str((config.get("paths", {}) or {}).get("index_file", "data/index.sqlite3"))
    index = Path(raw) if Path(raw).is_absolute() else ROOT / raw
    if not index.exists():
        return say(WARN, "Документы ещё не прочитаны",
                   "Это делается в интерфейсе кнопкой «Прочитать документы».")
    return say(OK, "Документы прочитаны")


def main() -> None:
    print("\nПроверка сервиса обновления документации\n")

    print("Что нужно, чтобы сервис вообще запустился:")
    base = [check_python(), check_packages(), check_ollama_app()]
    installed = ollama_models()
    base.append(check_ollama_running(installed))
    base.append(check_models(installed))

    print("\nЧто нужно, чтобы был виден интерфейс:")
    interface = check_design_system()

    print("\nЧто нужно для работы:")
    check_docs()
    check_index()

    print()
    if all(base) and interface:
        print("Всё готово. Запускайте:")
        print("    uvicorn backend.main:app --reload --port 8000")
        print("и откройте http://localhost:8000\n")
    elif all(base):
        print("Сервис запустится, но интерфейса не будет — поставьте дизайн-систему.\n")
    else:
        print("Сначала закройте пункты со знаком ✗ выше, потом запускайте сервис.\n")


if __name__ == "__main__":
    main()
