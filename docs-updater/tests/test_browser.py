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


def generate_and_wait(page, timeout: int = 120000) -> None:
    """Запускает генерацию и ждёт именно её конца: новый файл результата и активные кнопки."""
    previous = page.inner_text("#result-file")
    page.click("#generate")
    page.wait_for_function(
        """(previous) => {
            const file = document.querySelector('#result-file').textContent;
            const stats = document.querySelector('#diff-stats').textContent;
            return file && file !== previous && stats.includes('Изменено')
                && !document.querySelector('#download').disabled;
        }""",
        arg=previous,
        timeout=timeout,
    )


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
  index_file: "{tmp_path}/index.sqlite3"
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

        # обучение формату по образцу: один раз — и дальше применяется само
        sample = live_server["work"] / "sample-doc.md"
        sample.write_text(
            "# Настройка вебхуков\n\n## Назначение\n\nДокумент описывает подключение вебхуков.\n\n"
            "## Ограничения\n\n- Не более 5 вебхуков на проект.\n",
            encoding="utf-8",
        )
        page.set_input_files("#sample-files", str(sample))
        page.wait_for_function(
            "() => document.querySelectorAll('#samples-list [data-sample]').length === 1", timeout=30000
        )
        page.uncheck("#learn-with-model")
        page.click("#learn-format")
        page.wait_for_selector(".format-status--ok", timeout=60000)
        assert "Формат изучен по образцам" in page.inner_text("#format-status")
        assert "Применяется при каждой правке" in page.inner_text("#format-status")

        # поиск подставил найденный раздел — писателю не нужно искать его вручную
        page.wait_for_function(
            "() => document.querySelector('#section-hint').textContent.length > 0", timeout=30000
        )
        assert "подставлен поиском" in page.inner_text("#section-hint")
        assert page.eval_on_selector("#section-select option:checked", "e => e.textContent").strip() == (
            "— Срок жизни токена"
        )
        page.select_option("#section-select", index=0)  # дальше правим документ целиком

        # список разделов документа подтянулся
        page.wait_for_function("() => !document.querySelector('#section-select').disabled", timeout=30000)
        options = page.eval_on_selector_all("#section-select option", "els => els.map(e => e.textContent.trim())")
        assert options[0] == "весь документ целиком"
        assert any("Срок жизни токена" in option for option in options)

        # Шаг 4-5: обновление. Текст появляется потоком, ещё до готового diff
        previous_file = page.inner_text("#result-file")
        page.click("#generate")
        page.wait_for_function(
            "() => document.querySelector('#result-view').value.length > 0", timeout=60000
        )
        assert "модель пишет" in page.inner_text("#marks-info")
        page.wait_for_function(
            "(previous) => document.querySelector('#result-file').textContent !== previous"
            " && !document.querySelector('#download').disabled",
            arg=previous_file,
            timeout=120000,
        )
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
        generate_and_wait(page)
        assert "Изменено абзацев: 1" in page.inner_text("#diff-stats")

        # превью: документ в читаемом виде, новое подсвечено
        page.click(".tab[data-view='preview']")
        preview = page.inner_text("#preview-view")
        assert "Авторизация в API" in preview
        assert "#" not in preview  # разметка отрисована, а не показана как текст
        assert page.eval_on_selector_all("#preview-view h2", "els => els.length") >= 4
        highlighted = page.eval_on_selector_all("#preview-view ins", "els => els.map(e => e.textContent)")
        assert any("120" in text for text in highlighted)

        # удалённые куски показываются только по галочке
        live_server["ollama"].generate_response = (
            "# Авторизация в API\n\n## Назначение\n\n"
            "Документ описывает, как получить токен доступа и использовать его в запросах к публичному API."
        )
        page.select_option("#section-select", index=0)
        generate_and_wait(page)
        page.click(".tab[data-view='preview']")
        assert page.eval_on_selector_all(".preview__removed", "els => els.length") == 0
        page.check("#show-removed")
        assert page.eval_on_selector_all(".preview__removed", "els => els.length") > 0
        page.uncheck("#show-removed")

        # автопроверка оформления показана вместе с результатом
        assert not page.is_hidden("#checks-notes")
        assert "Автопроверка" in page.inner_text("#checks-notes")

        # проверка готового текста по гайду
        page.click("#review")
        page.wait_for_selector("#review-notes:not([hidden])", timeout=60000)
        assert "Замечания по гайду" in page.inner_text("#review-notes")
        assert page.eval_on_selector_all("#review-notes li", "els => els.length") == 2

        # сохранённые результаты видны на странице (список обновляется после генерации)
        page.wait_for_function(
            "() => document.querySelectorAll('.result-row').length >= 3", timeout=30000
        )
        rows = page.inner_text("#results-list")
        assert "api-auth.md" in rows
        assert "Срок жизни токена доступа увеличен" in rows

        browser.close()

    assert errors == [], f"Ошибки JS на странице: {errors}"
    assert external == [], f"Страница обратилась наружу: {external}"

    original = (live_server["work"] / "docs" / "api-auth.md").read_text(encoding="utf-8")
    assert "Токен действует 60 минут." in original, "Оригинал не должен меняться"
    assert list((live_server["work"] / "output").glob("*.md")), "Результат должен сохраниться отдельным файлом"
