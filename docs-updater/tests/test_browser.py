"""Проверка страницы в настоящем браузере: весь путь писателя от индексации до diff.

Запускается, только если установлен playwright и есть локальный Chromium
(`pip install playwright`). Иначе тест пропускается — обычный прогон от этого не зависит.
Сеть не используется: вместо Ollama работает локальная заглушка.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_ollama import FakeOllama  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
pytest.importorskip("playwright.sync_api", reason="playwright не установлен")


def find_chromium() -> str | None:
    if os.environ.get("CHROMIUM_PATH"):
        return os.environ["CHROMIUM_PATH"]
    roots = [Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")), Path.home() / ".cache/ms-playwright"]
    for root in roots:
        if root.exists():
            for candidate in sorted(root.glob("chromium*/chrome-linux/chrome")):
                return str(candidate)
            for candidate in sorted(root.glob("chromium*/chrome-mac/Chromium.app/Contents/MacOS/Chromium")):
                return str(candidate)
    return shutil.which("chromium") or shutil.which("google-chrome")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def live_server(tmp_path):
    chromium = find_chromium()
    if not chromium:
        pytest.skip("Локальный Chromium не найден")

    ollama = FakeOllama().start()
    ollama.chunk_delay = 0.15  # чтобы поток был виден в браузере, а не мгновенным
    shutil.copytree(REPO_ROOT / "data" / "docs", tmp_path / "docs")
    for name in ("styleguide.md", "style-rules.yaml", "template.schema.yaml", "glossary.yaml"):
        shutil.copy(REPO_ROOT / "data" / name, tmp_path / name)
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""ollama:
  host: "{ollama.host}"
  generation_model: "qwen3"
  embedding_model: "bge-m3"
  request_timeout: 60
paths:
  docs_dir: "{tmp_path}/docs"
  style_guide: "{tmp_path}/styleguide.md"
  style_guides: ["{tmp_path}/styleguide.md"]
  samples_dir: "{tmp_path}/samples"
  derived_guide: "{tmp_path}/derived-guide.md"
  index_file: "{tmp_path}/index.sqlite3"
  output_dir: "{tmp_path}/output"
  changesets_dir: "{tmp_path}/changesets"
  feedback_log: "{tmp_path}/feedback.jsonl"
search: {{top_k: 5, chunk_max_chars: 1800}}
generation: {{temperature: 0.2, num_ctx: 8192}}
languages:
  source: "ru"
  targets: ["en", "kk"]
  low_resource: ["kk"]
  layout: "folder"
  glossary: "{tmp_path}/glossary.yaml"
checks:
  prose_rules: "{tmp_path}/style-rules.yaml"
  template_schema: "{tmp_path}/template.schema.yaml"
  docs_config_dir: "{REPO_ROOT.parent}/docs-config"
  use_vale: false
  use_markdownlint: false
security:
  audit_log: "{tmp_path}/audit.jsonl"
""",
        encoding="utf-8",
    )

    port = free_port()
    env = {**os.environ, "DOCS_UPDATER_CONFIG": str(config)}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT,
        env=env,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.5)
    else:
        server.terminate()
        ollama.stop()
        pytest.fail("Сервер не запустился")

    yield {"url": f"http://127.0.0.1:{port}", "chromium": chromium, "work": tmp_path, "ollama": ollama}

    server.terminate()
    server.wait(timeout=10)
    ollama.stop()


def test_full_flow_in_browser(live_server):
    """Весь путь писателя мышкой: индекс → анализ → правка потоком → сравнение → замена оригинала."""
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    external: list[str] = []
    origin = live_server["url"].replace("http://", "")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=live_server["chromium"], args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        # Настоящие ошибки страницы ловит pageerror; коды ответа в консоли — не ошибка интерфейса.
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error" and "Failed to load resource" not in message.text
            else None,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: external.append(request.url)
            if origin not in request.url and not request.url.startswith("data:")
            else None,
        )

        page.goto(live_server["url"], wait_until="networkidle")
        page.wait_for_selector("[data-testid='ollama-status']", timeout=30000)
        # Статус подтягивается запросом: ждём именно его, а не первый кадр отрисовки.
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='ollama-status']\").innerText.includes('Ollama на связи')",
            timeout=30000,
        )

        # Интерфейс собран на дизайн-системе, а не на своей вёрстке.
        assert page.evaluate("() => typeof window.KasperskyHexaUi") == "object"

        # Шаг 1: индексация с экрана настроек
        page.click("[data-testid='nav-settings']")
        page.click("button:has-text('Прочитать документы')")
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='index-status']\").innerText.includes('Документы прочитаны')",
            timeout=90000,
        )
        assert "3 документа" in page.inner_text("[data-testid='index-info']")

        # Шаг 2: описание изменения и анализ
        page.click("[data-testid='nav-changed']")
        page.fill("textarea", "Срок жизни токена доступа увеличен с 60 до 120 минут")
        # Кнопка включается только когда описание дошло до состояния экрана.
        page.wait_for_selector("button:has-text('Найти документы'):not([disabled])", timeout=15000)
        page.click("button:has-text('Найти документы')")
        page.wait_for_selector("button:has-text('Обновить документ')", timeout=90000)
        assert "Что править" in page.inner_text("#root")

        # Шаг 3: выбор документа и потоковая правка
        page.click("button:has-text('Обновить документ')")
        page.wait_for_selector("text=Что править", timeout=30000)
        page.click("button:has-text('Переписать текст')")
        page.wait_for_selector("text=Проверка:", timeout=120000)

        # Шаг 4: результат — три способа посмотреть одно и то же
        page.click("button:has-text('Открыть результат')")
        page.wait_for_selector("text=Оригинал не тронут", timeout=30000)
        result_text = page.inner_text("#root")
        assert "добавлено" in result_text and "изменено" in result_text
        page.click("div[role='tab']:has-text('Предпросмотр')")
        page.wait_for_selector("text=Зелёным — то, что добавилось", timeout=15000)
        page.click("div[role='tab']:has-text('Готовый текст')")
        page.wait_for_selector("text=Меняется файл с правкой", timeout=15000)

        # Оставшиеся нарушения видны без дополнительных действий
        assert "Проверка по правилам" in page.inner_text("#root")

        # Шаг 5: замена оригинала — только через подтверждение
        page.click("button:has-text('Перезаписать оригинал')")
        page.wait_for_selector("text=Перезаписать оригинал?", timeout=15000)
        # Модальное окно рисуется порталом вне #root — читаем всю страницу.
        assert "резервную копию" in page.inner_text("body")
        page.click(".ant-modal button:has-text('Перезаписать оригинал')")
        page.wait_for_selector("text=Оригинал перезаписан", timeout=90000)
        backups = list((live_server["work"] / "docs").glob("*.bak-*"))
        assert backups, "перед заменой оригинала не создана резервная копия"

        browser.close()

    assert not errors, f"ошибки в браузере: {errors[:3]}"
    assert not external, f"страница обратилась наружу: {external[:3]}"


def test_changeset_flow_in_browser(live_server):
    """Набор отдельных правок: решение по каждой и сборка документа из принятых."""
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=live_server["chromium"], args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))

        page.goto(live_server["url"], wait_until="networkidle")
        page.click("[data-testid='nav-settings']")
        page.click("button:has-text('Прочитать документы')")
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='index-status']\").innerText.includes('Документы прочитаны')",
            timeout=90000,
        )

        page.click("[data-testid='nav-changed']")
        page.fill("textarea", "Срок жизни токена доступа увеличен с 60 до 120 минут")
        # Кнопка включается только когда описание дошло до состояния экрана.
        page.wait_for_selector("button:has-text('Найти документы'):not([disabled])", timeout=15000)
        page.click("button:has-text('Найти документы')")
        page.wait_for_selector("button:has-text('Обновить документ')", timeout=90000)
        page.click("button:has-text('Обновить документ')")

        page.click("button:has-text('Разобрать по одной')")
        page.click("button:has-text('Показать правки')")
        page.wait_for_selector("text=Предложено:", timeout=120000)

        # У каждой правки видно основание и решение
        body = page.inner_text("#root")
        assert "Взято из вашего описания" in body or "не смогла показать" in body
        page.click("button:has-text('Принять') >> nth=0")
        page.wait_for_selector("text=принята", timeout=30000)

        page.click("button:has-text('Собрать документ из принятых правок')")
        page.wait_for_selector("text=Оригинал не тронут", timeout=90000)
        assert "Что поменялось в тексте" in page.inner_text("#root")

        browser.close()

    assert not errors, f"ошибки в браузере: {errors[:3]}"


def test_page_without_design_system_explains_what_to_do(live_server):
    """Если файлов дизайн-системы нет, страница объясняет, что положить и куда."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=live_server["chromium"], args=["--no-sandbox"])
        page = browser.new_page()
        # Подменяем бандл пустым ответом: имитируем клон репозитория без vendor/hexa.
        page.route("**/vendor/hexa/_ds_bundle.js", lambda route: route.fulfill(status=404, body=""))
        page.goto(live_server["url"], wait_until="networkidle")
        page.wait_for_selector("text=Не найдена дизайн-система HEXA", timeout=15000)
        assert "vendor/hexa" in page.inner_text("#no-ds")
        browser.close()
