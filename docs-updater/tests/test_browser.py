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
    shutil.copytree(REPO_ROOT / "data" / "docs", tmp_path / "docs")
    shutil.copy(REPO_ROOT / "data" / "styleguide.md", tmp_path / "styleguide.md")
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
  index_file: "{tmp_path}/index.json"
  output_dir: "{tmp_path}/output"
search: {{top_k: 5, chunk_max_chars: 1800}}
generation: {{temperature: 0.2, num_ctx: 8192}}
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
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    external: list[str] = []
    origin = live_server["url"].replace("http://", "")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=live_server["chromium"], args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: external.append(request.url)
            if origin not in request.url and not request.url.startswith("data:")
            else None,
        )

        page.goto(live_server["url"], wait_until="networkidle")
        assert "Ollama на связи" in page.inner_text("#ollama-status")

        # Шаг 1: индексация
        page.click("#reindex")
        page.wait_for_selector("#overlay", state="hidden", timeout=60000)
        assert "3 док." in page.inner_text("#index-info")

        # Шаг 3: поиск документа
        page.fill("#change-text", "Срок жизни токена доступа увеличен с 60 до 120 минут")
        page.click("#find-doc")
        page.wait_for_selector(".candidate", timeout=60000)
        candidates = page.eval_on_selector_all(".candidate", "els => els.map(e => e.dataset.path)")
        assert candidates[0] == "api-auth.md"
        assert "api-auth.md" in page.inner_text("#chosen-doc")

        # список разделов документа подтянулся
        page.wait_for_function("() => !document.querySelector('#section-select').disabled", timeout=30000)
        options = page.eval_on_selector_all("#section-select option", "els => els.map(e => e.textContent.trim())")
        assert options[0] == "весь документ целиком"
        assert any("Срок жизни токена" in option for option in options)

        # Шаг 4-5: обновление и diff
        page.click("#generate")
        page.wait_for_selector("#step-diff:not([hidden])", timeout=120000)
        assert page.eval_on_selector_all("ins", "e => e.length") >= 1
        assert page.eval_on_selector_all("del", "e => e.length") >= 1
        assert "Изменено абзацев: 1" in page.inner_text("#diff-stats")

        # режим «только изменения» прячет неизменённые абзацы
        visible_before = page.eval_on_selector_all(".diff__equal", "els => els.filter(e => e.offsetParent).length")
        page.check("#only-changes")
        visible_after = page.eval_on_selector_all(".diff__equal", "els => els.filter(e => e.offsetParent).length")
        assert visible_before > 0 and visible_after == 0

        # вкладка с готовым документом: текст можно править прямо на странице
        page.click(".tab[data-view='result']")
        assert page.input_value("#result-view").startswith("# Авторизация в API")
        page.fill("#result-view", page.input_value("#result-view") + "\n\nДописано вручную.\n")
        page.click("#save-edits")
        page.wait_for_selector("#overlay", state="hidden", timeout=60000)
        page.click(".tab[data-view='diff']")
        assert "Добавлено: 1" in page.inner_text("#diff-stats")

        # правка одного раздела: выбираем раздел и обновляем только его
        page.select_option("#section-select", label="— Срок жизни токена")
        page.click("#generate")
        page.wait_for_selector("#overlay", state="hidden", timeout=120000)
        assert "Изменено абзацев: 1" in page.inner_text("#diff-stats")

        # сохранённые результаты видны на странице
        assert page.eval_on_selector_all(".result-row", "els => els.length") >= 2

        browser.close()

    assert errors == [], f"Ошибки JS на странице: {errors}"
    assert external == [], f"Страница обратилась наружу: {external}"

    original = (live_server["work"] / "docs" / "api-auth.md").read_text(encoding="utf-8")
    assert "Токен действует 60 минут." in original, "Оригинал не должен меняться"
    assert list((live_server["work"] / "output").glob("*.md")), "Результат должен сохраниться отдельным файлом"
