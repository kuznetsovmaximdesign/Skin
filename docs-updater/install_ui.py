"""Установка дизайн-системы HEXA в интерфейс сервиса.

Интерфейс собран на компонентах HEXA. Сами файлы дизайн-системы — внутренние, в
репозиторий они не выкладываются, поэтому их нужно один раз положить рядом.

Как пользоваться:

    python3 install_ui.py путь/до/выгрузки-дизайна.zip

Скрипт возьмёт из выгрузки папку _ds/kaspersky-hexa-ui-…/ и скопирует нужные файлы
в frontend/vendor/hexa/. Интернет не нужен.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "frontend" / "vendor" / "hexa"
NEEDED = ("_ds_bundle.js", "_ds_bundle.css", "styles.css", "fonts/fonts.css")

# Стили бандла подключают два файла, которых в поставке нет: терминал и сторонний diff.
# Сервис их не использует, а браузер из-за них ругается — поэтому отключаем.
MISSING_IMPORTS = (
    '@import "@xterm/xterm/css/xterm.css";',
    '@import "react-diff-view/style/index.css";',
)


def copy_from_folder(source: Path) -> list[str]:
    copied = []
    for name in NEEDED:
        origin = source / name
        if not origin.exists():
            raise SystemExit(f"В выгрузке нет файла {name}. Проверьте, что это папка дизайн-системы.")
        destination = TARGET / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origin, destination)
        copied.append(name)
    return copied


def copy_from_zip(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zip_file:
        names = zip_file.namelist()
        prefix = next(
            (name.rsplit("_ds_bundle.js", 1)[0] for name in names if name.endswith("_ds_bundle.js")),
            None,
        )
        if prefix is None:
            raise SystemExit("В архиве нет файла _ds_bundle.js — это не выгрузка дизайн-системы.")
        copied = []
        for name in NEEDED:
            inside = prefix + name
            if inside not in names:
                raise SystemExit(f"В архиве нет файла {name}.")
            destination = TARGET / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zip_file.read(inside))
            copied.append(name)
        return copied


def disable_missing_imports() -> None:
    css = TARGET / "_ds_bundle.css"
    text = css.read_text(encoding="utf-8")
    for missing in MISSING_IMPORTS:
        text = text.replace(missing, f"/* отключено: файла нет в поставке — {missing} */")
    css.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Укажите путь к выгрузке дизайн-системы: python3 install_ui.py выгрузка.zip")

    source = Path(sys.argv[1]).expanduser()
    if not source.exists():
        raise SystemExit(f"Не найден путь: {source}")

    TARGET.mkdir(parents=True, exist_ok=True)
    copied = copy_from_zip(source) if source.suffix == ".zip" else copy_from_folder(source)
    disable_missing_imports()

    print("Дизайн-система установлена в", TARGET)
    for name in copied:
        size = (TARGET / name).stat().st_size // 1024
        print(f"  {name} — {size} КБ")
    print("Готово. Запустите сервис и откройте http://localhost:8000")


if __name__ == "__main__":
    main()
