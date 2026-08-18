"""Тесты сервиса. Работают полностью офлайн: вместо Ollama — локальная заглушка."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config as config_module  # noqa: E402
from backend.diffing import build_diff, split_paragraphs  # noqa: E402
from backend.generator import build_prompt, check_result  # noqa: E402
from backend.ollama_client import clean_model_output  # noqa: E402
from backend.search import cosine, to_percent  # noqa: E402
from tests.fake_ollama import FakeOllama  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def fake_ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture()
def client(tmp_path, monkeypatch, fake_ollama):
    """Изолированная копия проекта в tmp: свои config.yaml, docs, styleguide."""
    shutil.copytree(REPO_ROOT / "data" / "docs", tmp_path / "docs")
    shutil.copy(REPO_ROOT / "data" / "styleguide.md", tmp_path / "styleguide.md")

    config = {
        "ollama": {
            "host": fake_ollama.host,
            "generation_model": "qwen3",
            "embedding_model": "bge-m3",
            "request_timeout": 30,
        },
        "paths": {
            "docs_dir": "docs",
            "style_guide": "styleguide.md",
            "index_file": "index.json",
            "output_dir": "output",
        },
        "search": {"top_k": 5, "chunk_max_chars": 1800},
        "generation": {"temperature": 0.2, "num_ctx": 8192},
    }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.yaml")

    from backend.main import app

    with TestClient(app) as test_client:
        test_client.tmp_path = tmp_path
        test_client.ollama = fake_ollama
        yield test_client


# --- статус ----------------------------------------------------------------


def test_status_ok(client):
    data = client.get("/api/status").json()
    assert data["ollama"]["available"] is True
    assert data["ollama"]["generation_model_installed"] is True
    assert data["markdown_files"] == 3
    assert data["index"]["exists"] is False


def test_status_when_ollama_is_down(client):
    client.ollama.stop()
    data = client.get("/api/status").json()
    assert data["ollama"]["available"] is False
    assert "не удалось подключиться" in data["ollama"]["error"].lower()
    assert "ollama serve" in data["ollama"]["hint"]


def test_status_when_model_is_missing(client):
    client.ollama.models = ["bge-m3:latest"]
    data = client.get("/api/status").json()
    assert data["ollama"]["generation_model_installed"] is False


# --- индексация ------------------------------------------------------------


def test_reindex_builds_local_index(client):
    data = client.post("/api/reindex").json()
    assert data["documents_count"] == 3
    assert data["sections_count"] > 5
    assert (client.tmp_path / "index.json").exists()


def test_reindex_reports_missing_model_with_pull_command(client):
    client.ollama.models = ["qwen3:latest"]  # эмбеддингов нет
    response = client.post("/api/reindex")
    assert response.status_code == 503
    assert "ollama pull bge-m3" in response.json()["hint"]


def test_reindex_reports_ollama_down(client):
    client.ollama.stop()
    response = client.post("/api/reindex")
    assert response.status_code == 503
    assert "ollama serve" in response.json()["hint"]


def test_reindex_on_empty_folder(client):
    for path in (client.tmp_path / "docs").glob("*.md"):
        path.unlink()
    response = client.post("/api/reindex")
    assert response.status_code == 400
    assert "нет файлов" in response.json()["detail"]


# --- поиск -----------------------------------------------------------------


def test_search_requires_index(client):
    response = client.post("/api/search", json={"query": "токен"})
    assert response.status_code == 400
    assert "Переиндексировать" in response.json()["detail"]


def test_search_finds_the_right_document(client):
    client.post("/api/reindex")
    query = "срок жизни токена доступа увеличен, добавлен отзыв токена"
    candidates = client.post("/api/search", json={"query": query}).json()["candidates"]
    assert candidates[0]["path"] == "api-auth.md"
    assert 0 <= candidates[0]["relevance"] <= 100
    assert candidates[0]["snippet"]
    assert len(candidates) <= 5
    # кандидаты отсортированы по убыванию релевантности
    assert candidates == sorted(candidates, key=lambda item: -item["score"])


def test_search_returns_several_candidates(client):
    client.post("/api/reindex")
    candidates = client.post("/api/search", json={"query": "экспорт отчёта в формате CSV"}).json()["candidates"]
    assert candidates[0]["path"] == "export-reports.md"
    assert len(candidates) == 3  # столько документов в папке


# --- генерация -------------------------------------------------------------


def test_generate_keeps_original_untouched(client):
    client.post("/api/reindex")
    original = (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")

    data = client.post(
        "/api/generate",
        json={"doc_path": "api-auth.md", "change_description": "Срок жизни токена — 120 минут."},
    ).json()

    assert (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8") == original
    assert "120 минут" in data["updated"]
    assert data["diff"]["has_changes"] is True
    assert data["style_guide_used"] is True
    result_file = client.tmp_path / "output" / data["result_file"]
    assert result_file.exists()
    assert result_file.read_text(encoding="utf-8") == data["updated"]


def test_generate_strips_thinking_and_fences(client):
    client.ollama.generate_response = "<think>ага</think>\n```markdown\n# Итог\n\nТекст.\n```"
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    assert data["updated"].startswith("# Итог")
    assert "```" not in data["updated"]
    assert "think" not in data["updated"]


def test_generate_prompt_contains_guide_and_change(client):
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "новая правка"})
    prompt = client.ollama.requests[-1]["payload"]["prompt"]
    assert "ГАЙД ПО СТИЛЮ" in prompt
    assert "Гайд по стилю технической документации" in prompt
    assert "новая правка" in prompt
    assert "Авторизация в API" in prompt


def test_generate_warns_when_document_shrinks(client):
    client.ollama.generate_response = "# Авторизация в API\n\nКоротко."
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    assert any("короче" in warning for warning in data["warnings"])
    assert any("заголовки" in warning for warning in data["warnings"])


def test_generate_reports_missing_generation_model(client):
    client.ollama.models = ["bge-m3:latest"]
    response = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    )
    assert response.status_code == 503
    assert "ollama pull qwen3" in response.json()["hint"]


def test_generate_unknown_document(client):
    response = client.post("/api/generate", json={"doc_path": "нет-такого.md", "change_description": "x"})
    assert response.status_code == 404


def test_path_traversal_is_blocked(client):
    response = client.get("/api/document", params={"path": "../config.yaml"})
    assert response.status_code == 400


# --- скачивание и применение ----------------------------------------------


def test_download_updated_file(client):
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    response = client.get("/api/download", params={"file": data["result_file"]})
    assert response.status_code == 200
    assert response.text == data["updated"]


def test_apply_makes_backup_and_overwrites(client):
    original = (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()

    applied = client.post(
        "/api/apply", json={"doc_path": "api-auth.md", "result_path": data["result_file"]}
    ).json()

    assert applied["applied"] is True
    assert (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8") == data["updated"]
    backup = client.tmp_path / "docs" / applied["backup"]
    assert backup.exists() and backup.read_text(encoding="utf-8") == original


# --- гайд и настройки ------------------------------------------------------


def test_style_guide_read_write_and_upload(client):
    assert "Гайд по стилю" in client.get("/api/style-guide").json()["content"]

    client.put("/api/style-guide", json={"content": "# Новый гайд\n\nПишите коротко."})
    assert "Новый гайд" in (client.tmp_path / "styleguide.md").read_text(encoding="utf-8")

    response = client.post(
        "/api/style-guide/upload",
        files={"file": ("guide.md", b"# \xd0\x93\xd0\xb0\xd0\xb9\xd0\xb4 2", "text/markdown")},
    )
    assert response.status_code == 200
    assert "Гайд 2" in response.json()["content"]

    bad = client.post("/api/style-guide/upload", files={"file": ("guide.pdf", b"x", "application/pdf")})
    assert bad.status_code == 400


def test_config_update_switches_docs_folder(client):
    other = client.tmp_path / "other-docs"
    other.mkdir()
    (other / "readme.md").write_text("# Другая папка\n\nТекст.", encoding="utf-8")

    data = client.post("/api/config", json={"docs_dir": str(other), "generation_model": "qwen3:8b"}).json()
    assert data["markdown_files"] == 1
    assert data["config"]["generation_model"] == "qwen3:8b"
    assert yaml.safe_load((client.tmp_path / "config.yaml").read_text())["paths"]["docs_dir"] == str(other)


def test_documents_listing(client):
    documents = client.get("/api/documents").json()["documents"]
    assert {doc["path"] for doc in documents} == {"api-auth.md", "export-reports.md", "install-agent.md"}
    assert any(doc["title"] == "Авторизация в API" for doc in documents)


def test_frontend_is_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Обновление документации" in page.text
    # никаких внешних адресов на странице
    assert "http://" not in page.text.replace("http://localhost", "")
    assert "https://" not in page.text


# --- модульные проверки ----------------------------------------------------


def test_diff_marks_changed_added_and_removed():
    diff = build_diff(
        "Первый абзац.\n\nВторой абзац.\n\nЛишний абзац.",
        "Первый абзац.\n\nВторой абзац изменён.\n\nСовсем новый абзац в конце.",
    )
    assert diff["stats"]["unchanged"] == 1
    assert diff["stats"]["changed"] == 2
    assert diff["stats"]["removed"] == 0
    assert diff["stats"]["added"] == 0

    grew = build_diff("Первый абзац.", "Первый абзац.\n\nДобавленный абзац.")
    assert grew["stats"]["added"] == 1
    shrank = build_diff("Первый абзац.\n\nЛишний абзац.", "Первый абзац.")
    assert shrank["stats"]["removed"] == 1
    changed = next(block for block in diff["blocks"] if block["type"] == "replace")
    assert any(part["type"] == "added" for part in changed["inline"]["new"])


def test_diff_no_changes():
    diff = build_diff("Один.\n\nДва.", "Один.\n\nДва.")
    assert diff["has_changes"] is False


def test_split_paragraphs_ignores_empty():
    assert split_paragraphs("A\n\n\n\nB\n") == ["A", "B"]


def test_clean_model_output():
    assert clean_model_output("<think>x</think>\n# Док") == "# Док"
    assert clean_model_output("```md\n# Док\n\nТекст\n```") == "# Док\n\nТекст"


def test_check_result_flags_placeholders():
    warnings = check_result("# Док\n\nТекст", "# Док\n\nТекст [уточнить] и [спорно: конфликт с гайдом]")
    assert any("уточнить" in warning for warning in warnings)
    assert any("спорно" in warning for warning in warnings)


def test_build_prompt_without_guide():
    prompt = build_prompt("# Док", "изменение", "", "doc.md")
    assert "гайд по стилю не подключён" in prompt


def test_cosine_and_percent():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert to_percent(1.0) == 100
    assert to_percent(-1.0) == 0


# --- гарантия офлайна ------------------------------------------------------


def test_no_external_urls_in_sources():
    """В коде не должно быть адресов, кроме локального Ollama: сервис работает офлайн."""
    import re as regex

    allowed = ("localhost", "127.0.0.1", "0.0.0.0", "api.example.local")
    files = [
        *(REPO_ROOT / "backend").glob("*.py"),
        *(REPO_ROOT / "frontend").glob("*.*"),
        REPO_ROOT / "config.yaml",
    ]
    external: list[str] = []
    for path in files:
        for url in regex.findall(r"https?://[^\s\"'`)<>]+", path.read_text(encoding="utf-8")):
            if not any(host in url for host in allowed):
                external.append(f"{path.name}: {url}")
    assert not external, f"Найдены внешние адреса: {external}"


def test_frontend_has_no_external_assets():
    """Фронтенд не тянет шрифты, скрипты и стили из сети."""
    html = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "cdn" not in html.lower()
    assert "fonts.googleapis" not in html
    for tag in ("src=", "href="):
        for value in [part.split('"')[1] for part in html.split(tag)[1:] if '"' in part]:
            assert not value.startswith(("http://", "https://", "//")), value
