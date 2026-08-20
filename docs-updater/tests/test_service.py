"""Тесты сервиса. Работают полностью офлайн: вместо Ollama — локальная заглушка."""

from __future__ import annotations

import json as json_module
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config as config_module  # noqa: E402
from backend import index_store  # noqa: E402
from backend.diffing import build_diff, split_paragraphs  # noqa: E402
from backend.generator import build_prompt, check_context_size, check_result  # noqa: E402
from backend.ollama_client import clean_model_output  # noqa: E402
from backend.sections import outline, replace_section, section_text  # noqa: E402
from backend.search import cosine, to_percent  # noqa: E402
from tests.fake_ollama import FakeOllama  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def last_prompt(ollama, marker: str) -> str:
    """Последний промпт, содержащий маркер: после генерации бывает ещё запрос на починку."""
    for request in reversed(ollama.requests):
        prompt = request["payload"].get("prompt", "")
        if marker in prompt:
            return prompt
    raise AssertionError(f"нет запроса с маркером {marker}")


def indexed_sections(client, doc_path: str) -> list[str]:
    """Тексты секций документа прямо из локального индекса (SQLite)."""
    with index_store.connect(client.tmp_path / "index.sqlite3") as connection:
        rows = connection.execute(
            "SELECT text FROM sections WHERE doc_path = ?", (doc_path,)
        ).fetchall()
    return [row[0] for row in rows]


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
    # Правила формулировки и шаблон статьи — как в настоящей установке
    shutil.copy(REPO_ROOT / "data" / "style-rules.yaml", tmp_path / "style-rules.yaml")
    shutil.copy(REPO_ROOT / "data" / "template.schema.yaml", tmp_path / "template.schema.yaml")
    shutil.copy(REPO_ROOT / "data" / "glossary.yaml", tmp_path / "glossary.yaml")

    config = {
        "ollama": {
            "host": fake_ollama.host,
            "generation_model": "qwen3:4b",
            "embedding_model": "bge-m3",
            "keep_alive": "5m",
            "sequential_models": True,
            "request_timeout": 30,
        },
        "paths": {
            "docs_dir": "docs",
            "style_guide": "styleguide.md",
            "style_guides": ["styleguide.md"],
            "samples_dir": "samples",
            "rules_dir": "rules",
            "derived_guide": "derived-guide.md",
            "changesets_dir": "changesets",
            "feedback_log": "feedback.jsonl",
            "use_derived_guide": True,
            "index_file": "index.sqlite3",
            "output_dir": "output",
        },
        "search": {"top_k": 5, "chunk_max_chars": 1800, "embed_batch": 8},
        "generation": {"temperature": 0.2, "num_ctx": 8192},
        "security": {
            "auth": "none",
            "tokens": {},
            "default_role": "writer",
            "roles": {
                "writer": {"classifications": ["public", "internal"]},
                "lead": {"classifications": ["public", "internal", "confidential"]},
            },
            "confidential_paths": ["secret/*"],
            "default_classification": "internal",
            "audit": True,
            "audit_log": "audit.jsonl",
        },
        "languages": {
            "source": "ru",
            "targets": ["en", "kk"],
            "layout": "folder",
            "low_resource": ["kk"],
            "glossary": "glossary.yaml",
        },
        "checks": {
            "enabled": True,
            "builtin_prose": True,
            "builtin_markdown": True,
            "schema": True,
            "prose_rules": "style-rules.yaml",
            "template_schema": "template.schema.yaml",
            # артефакты разбора портала лежат в репозитории
            "docs_config_dir": str(REPO_ROOT.parent / "docs-config"),
            "max_line_length": 120,
            "bullet_marker": "-",
            "require_fence_language": True,
            # внешние линтеры в тестах не используем: проверяем встроенные правила
            "use_vale": False,
            "use_markdownlint": False,
            "max_fix_iterations": 2,
        },
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
    assert (client.tmp_path / "index.sqlite3").exists()


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


def test_reindex_reuses_embeddings_for_unchanged_sections(client):
    first = client.post("/api/reindex").json()
    assert first["reused_sections"] == 0
    assert first["computed_sections"] == first["sections_count"]

    embed_calls_before = len([r for r in client.ollama.requests if "embed" in r["path"]])

    # меняем один документ — пересчитаться должны только его секции
    doc = client.tmp_path / "docs" / "api-auth.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("60 минут", "120 минут"), encoding="utf-8")

    second = client.post("/api/reindex").json()
    assert second["computed_sections"] == 1
    assert second["reused_sections"] == second["sections_count"] - 1
    embed_calls_after = len([r for r in client.ollama.requests if "embed" in r["path"]])
    assert embed_calls_after - embed_calls_before == 1


def test_reindex_recomputes_everything_when_model_changes(client):
    first = client.post("/api/reindex").json()
    client.ollama.models = ["qwen3:latest", "bge-m3:latest", "nomic-embed-text:latest"]
    client.post("/api/config", json={"embedding_model": "nomic-embed-text"})

    second = client.post("/api/reindex").json()
    assert second["reused_sections"] == 0
    assert second["computed_sections"] == first["sections_count"]


def test_reindex_drops_deleted_documents(client):
    client.post("/api/reindex")
    (client.tmp_path / "docs" / "export-reports.md").unlink()
    second = client.post("/api/reindex").json()
    assert second["documents_count"] == 2
    assert {doc["path"] for doc in second["documents"]} == {"api-auth.md", "install-agent.md"}


# --- поиск -----------------------------------------------------------------


def test_search_requires_index(client):
    response = client.post("/api/search", json={"query": "токен"})
    assert response.status_code == 400
    assert "Прочитать документы" in response.json()["detail"]


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
    prompt = last_prompt(client.ollama, "ИСХОДНЫЙ ДОКУМЕНТ")
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


def test_apply_refreshes_index(client):
    client.post("/api/reindex")
    data = client.post(
        "/api/generate",
        json={"doc_path": "api-auth.md", "change_description": "Срок жизни токена — 120 минут."},
    ).json()

    applied = client.post(
        "/api/apply", json={"doc_path": "api-auth.md", "result_path": data["result_file"]}
    ).json()

    assert applied["index_updated"] is True
    texts = " ".join(indexed_sections(client, "api-auth.md"))
    assert "120 минут" in texts


def test_apply_without_ollama_keeps_working(client):
    client.post("/api/reindex")
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    client.ollama.stop()

    applied = client.post(
        "/api/apply", json={"doc_path": "api-auth.md", "result_path": data["result_file"]}
    ).json()
    assert applied["applied"] is True
    assert applied["index_updated"] is False


def test_results_history(client):
    assert client.get("/api/results").json()["results"] == []

    for description in ("первая правка", "вторая правка"):
        client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": description})

    results = client.get("/api/results").json()["results"]
    assert len(results) == 2
    assert all(item["file"].endswith(".md") and item["size"] > 0 for item in results)
    assert results[0]["saved_at"] >= results[1]["saved_at"]


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


def test_check_context_size_warns_when_document_is_too_big():
    assert check_context_size("x" * 300, "x" * 300, num_ctx=16384) == []
    warnings = check_context_size("x" * 90000, "x" * 60000, num_ctx=8192)
    assert warnings and "num_ctx" in warnings[0]


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
        *(REPO_ROOT / "backend" / "checks").glob("*.py"),
        *(REPO_ROOT / "frontend").glob("*.*"),
    ]
    external: list[str] = []
    for path in files:
        for url in regex.findall(r"https?://[^\s\"'`)<>]+", path.read_text(encoding="utf-8")):
            if not any(host in url for host in allowed):
                external.append(f"{path.name}: {url}")
    assert not external, f"Найдены внешние адреса: {external}"


def test_publishing_is_disabled_and_addressless_by_default():
    """Адреса площадок задаёт пользователь. По умолчанию наружу идти некуда и нечему."""
    import re as regex

    raw = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    settings = yaml.safe_load(raw)

    assert settings["publish"]["enabled"] is False
    assert settings["publish"]["confluence"]["base_url"] == ""
    assert settings["publish"]["portal"]["base_url"] == ""
    # токены не хранятся в файле — только имена переменных окружения
    assert settings["publish"]["confluence"]["auth_env"] == "CONFLUENCE_TOKEN"
    assert "token:" not in raw.lower()

    # вне комментариев-примеров внешних адресов в конфиге нет
    active_lines = []
    for line in raw.splitlines():
        if line.strip().startswith("#"):
            continue
        active_lines.append(line.split(" #", 1)[0])
    active = "\n".join(active_lines)
    urls = [
        url for url in regex.findall(r"https?://[^\s\"'`)<>]+", active)
        if "localhost" not in url and "127.0.0.1" not in url
    ]
    assert urls == [], urls


def test_frontend_has_no_external_assets():
    """Фронтенд не тянет шрифты, скрипты и стили из сети."""
    html = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "cdn" not in html.lower()
    assert "fonts.googleapis" not in html
    for tag in ("src=", "href="):
        for value in [part.split('"')[1] for part in html.split(tag)[1:] if '"' in part]:
            assert not value.startswith(("http://", "https://", "//")), value


def test_two_results_in_the_same_second_do_not_overwrite(client):
    first = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "первая"}
    ).json()
    client.ollama.generate_response = "# Авторизация в API\n\nВторой вариант текста документа."
    second = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "вторая"}
    ).json()

    assert first["result_file"] != second["result_file"]
    output = client.tmp_path / "output"
    assert (output / first["result_file"]).read_text(encoding="utf-8") == first["updated"]
    assert (output / second["result_file"]).read_text(encoding="utf-8") == second["updated"]


# --- правка одного раздела -------------------------------------------------


def test_outline_lists_sections(client):
    data = client.get("/api/outline", params={"path": "api-auth.md"}).json()
    titles = [section["title"] for section in data["sections"]]
    assert titles == [
        "Авторизация в API",
        "Назначение",
        "Предварительные условия",
        "Получение токена",
        "Срок жизни токена",
        "Ограничения",
    ]
    assert all(section["chars"] > 0 for section in data["sections"])


def test_generate_updates_only_the_chosen_section(client):
    original = (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")
    target_index = 4  # «Срок жизни токена»

    data = client.post(
        "/api/generate",
        json={
            "doc_path": "api-auth.md",
            "change_description": "Срок жизни токена — 120 минут.",
            "section_index": target_index,
        },
    ).json()

    assert data["mode"] == "section"
    assert data["section"] == "Авторизация в API > Срок жизни токена"
    assert "120 минут" in data["updated"]

    # все разделы, кроме выбранного, остались дословно теми же
    # (родительский раздел «Авторизация в API» содержит выбранный, поэтому его пропускаем)
    spans_before = outline(original)
    spans_after = outline(data["updated"])
    assert len(spans_before) == len(spans_after)
    target = spans_before[target_index]
    compared = 0
    for before, after in zip(spans_before, spans_after):
        contains_target = before.start <= target.start and before.end >= target.end
        if contains_target:
            continue
        assert section_text(original, before) == section_text(data["updated"], after)
        compared += 1
    assert compared == 4  # четыре нетронутых раздела рядом

    # в модель уходил только раздел, а не весь документ
    prompt = last_prompt(client.ollama, "РАЗДЕЛ, КОТОРЫЙ НУЖНО ОБНОВИТЬ")
    assert "Предварительные условия\n\n- Учётная запись" not in prompt


def test_generate_with_unknown_section(client):
    response = client.post(
        "/api/generate",
        json={"doc_path": "api-auth.md", "change_description": "правка", "section_index": 99},
    )
    assert response.status_code == 400
    assert "раздела нет" in response.json()["detail"]


def test_manual_edits_are_saved_and_rediffed(client):
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    edited = data["updated"].replace("120 минут", "90 минут") + "\n\nДописано вручную.\n"

    saved = client.post(
        "/api/results/save",
        json={"doc_path": "api-auth.md", "result_file": data["result_file"], "content": edited},
    ).json()

    assert saved["result_file"] == data["result_file"]
    assert (client.tmp_path / "output" / data["result_file"]).read_text(encoding="utf-8") == edited
    assert saved["diff"]["stats"]["added"] >= 1
    # оригинал по-прежнему нетронут
    assert "60 минут" in (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")


def test_manual_edits_reject_unknown_result(client):
    response = client.post(
        "/api/results/save",
        json={"doc_path": "api-auth.md", "result_file": "нет-такого.md", "content": "текст"},
    )
    assert response.status_code == 404


# --- разбор разделов -------------------------------------------------------


def test_outline_ignores_headings_inside_code_fences():
    content = "# Док\n\nТекст.\n\n```bash\n# это команда, не заголовок\n```\n\n## Раздел\n\nЕщё текст."
    spans = outline(content)
    assert [span.title for span in spans] == ["Док", "Раздел"]


def test_outline_nests_levels():
    content = "# A\n\nтекст\n\n## B\n\nтекст\n\n### C\n\nтекст\n\n## D\n\nтекст"
    spans = outline(content)
    assert [span.path for span in spans] == ["A", "A > B", "A > B > C", "A > D"]
    # раздел B заканчивается там, где начинается D, и включает вложенный C
    assert "### C" in section_text(content, spans[1])
    assert "## D" not in section_text(content, spans[1])


def test_replace_section_keeps_the_rest_intact():
    content = "# A\n\nпервый\n\n## B\n\nвторой\n\n## C\n\nтретий"
    spans = outline(content)
    updated = replace_section(content, spans[1], "## B\n\nвторой обновлённый")
    assert updated == "# A\n\nпервый\n\n## B\n\nвторой обновлённый\n\n## C\n\nтретий"


def test_results_carry_the_change_description(client):
    client.post(
        "/api/generate",
        json={
            "doc_path": "api-auth.md",
            "change_description": "Срок жизни токена — 120 минут.",
            "section_index": 4,
        },
    )
    item = client.get("/api/results").json()["results"][0]
    assert item["doc_path"] == "api-auth.md"
    assert item["change_description"] == "Срок жизни токена — 120 минут."
    assert item["mode"] == "section"
    assert item["section"].endswith("Срок жизни токена")
    assert item["model"] == "qwen3:4b"
    assert "edited_at" not in item


def test_manual_edit_is_marked_in_results(client):
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    client.post(
        "/api/results/save",
        json={"doc_path": "api-auth.md", "result_file": data["result_file"], "content": "# Док\n\nТекст."},
    )
    item = client.get("/api/results").json()["results"][0]
    assert item["edited_at"]
    assert item["change_description"] == "правка"


def test_meta_files_are_not_listed_as_results(client):
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})
    results = client.get("/api/results").json()["results"]
    assert len(results) == 1
    assert all(not item["file"].endswith(".json") for item in results)


# --- потоковая генерация ---------------------------------------------------


def read_stream(response) -> list[dict]:
    return [json_module.loads(line) for line in response.text.splitlines() if line.strip()]


def test_generate_stream_sends_text_as_it_comes(client):
    with client.stream(
        "POST",
        "/api/generate/stream",
        json={"doc_path": "api-auth.md", "change_description": "Срок жизни токена — 120 минут."},
    ) as response:
        assert response.status_code == 200
        events = [json_module.loads(line) for line in response.iter_lines() if line.strip()]

    kinds = [event["type"] for event in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert kinds.count("chunk") > 1  # текст пришёл несколькими порциями

    streamed = "".join(event["text"] for event in events if event["type"] == "chunk")
    assert "120 минут" in streamed
    assert "<think>" not in streamed and "рассуждения модели" not in streamed

    done = events[-1]
    assert done["updated"].startswith("# Авторизация в API")
    assert done["diff"]["has_changes"] is True
    assert (client.tmp_path / "output" / done["result_file"]).exists()
    assert "60 минут" in (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")


def test_generate_stream_for_a_single_section(client):
    with client.stream(
        "POST",
        "/api/generate/stream",
        json={
            "doc_path": "api-auth.md",
            "change_description": "Срок жизни токена — 120 минут.",
            "section_index": 4,
        },
    ) as response:
        events = [json_module.loads(line) for line in response.iter_lines() if line.strip()]

    assert events[0]["mode"] == "section"
    done = events[-1]
    assert done["type"] == "done"
    assert done["updated"].count("## Ограничения") == 1
    assert "120 минут" in done["updated"]


def test_generate_stream_reports_missing_model_before_streaming(client):
    client.ollama.models = ["bge-m3:latest"]
    response = client.post(
        "/api/generate/stream", json={"doc_path": "api-auth.md", "change_description": "правка"}
    )
    assert response.status_code == 503
    assert "ollama pull qwen3" in response.json()["hint"]


def test_generate_stream_reports_empty_answer(client):
    client.ollama.generate_response = "   "
    response = client.post(
        "/api/generate/stream", json={"doc_path": "api-auth.md", "change_description": "правка"}
    )
    events = read_stream(response)
    assert events[-1]["type"] == "error"
    assert "пустой ответ" in events[-1]["error"]


def test_think_filter_survives_split_tags():
    from backend.ollama_client import ThinkFilter

    filtered = ThinkFilter()
    parts = ["Начало ", "<thi", "nk>рассуж", "дения</thi", "nk>", " конец"]
    assert "".join(filtered.feed(part) for part in parts) + filtered.flush() == "Начало  конец"


# --- проверка по гайду -----------------------------------------------------


def test_review_returns_notes(client):
    data = client.post("/api/review", json={"content": "# Док\n\nТокен действует 120 минут."}).json()
    assert data["notes"] == [
        "«Токен действует 120 минут.» — по гайду версии пишем полностью",
        "«Не более 10 запросов» — уточните единицу времени",
    ]
    assert data["model"] == "qwen3:4b"

    prompt = client.ollama.requests[-1]["payload"]["prompt"]
    assert "ПРОВЕРКА ПО ГАЙДУ" in prompt
    assert "Гайд по стилю технической документации" in prompt


def test_review_without_style_guide(client):
    client.put("/api/style-guide", json={"content": "   "})
    response = client.post("/api/review", json={"content": "# Док\n\nТекст."})
    assert response.status_code == 400
    assert "Правила оформления пустые" in response.json()["detail"]


def test_review_reports_missing_model(client):
    client.ollama.models = ["bge-m3:latest"]
    response = client.post("/api/review", json={"content": "# Док"})
    assert response.status_code == 503
    assert "ollama pull qwen3" in response.json()["hint"]


def test_review_when_nothing_found(client):
    client.ollama.review_response = "Нарушений не найдено"
    data = client.post("/api/review", json={"content": "# Док\n\nТекст."}).json()
    assert data["notes"] == []


def test_search_candidates_expose_the_matching_section(client):
    client.post("/api/reindex")
    candidates = client.post(
        "/api/search", json={"query": "срок жизни токена доступа увеличен"}
    ).json()["candidates"]
    assert candidates[0]["heading"] == "Авторизация в API > Срок жизни токена"
    # такой же путь есть в оглавлении документа — значит раздел можно подставить автоматически
    outline_paths = [
        section["path"] for section in client.get("/api/outline", params={"path": "api-auth.md"}).json()["sections"]
    ]
    assert candidates[0]["heading"] in outline_paths


# --- работа на 18 ГБ: батчи, keep_alive, по одной модели за раз ------------


def test_embeddings_are_sent_in_small_batches(client):
    client.post("/api/config", json={})  # конфиг из фикстуры: embed_batch = 3
    config_path = client.tmp_path / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("embed_batch: 8", "embed_batch: 3"),
        encoding="utf-8",
    )

    client.post("/api/reindex")
    batches = [
        len(request["payload"]["input"])
        for request in client.ollama.requests
        if request["path"] == "/api/embed"
    ]
    assert batches, "эмбеддинги должны считаться через /api/embed"
    assert max(batches) <= 3, f"батчи оказались больше лимита: {batches}"
    assert sum(batches) == client.get("/api/status").json()["index"]["sections_count"]


def test_keep_alive_is_sent_with_every_request(client):
    client.post("/api/reindex")
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})

    embeds = [r for r in client.ollama.requests if r["path"] == "/api/embed"]
    generations = [
        r for r in client.ollama.requests if r["path"] == "/api/generate" and r["payload"].get("prompt")
    ]
    assert embeds and generations
    assert all(request["payload"].get("keep_alive") == "5m" for request in embeds)
    assert all(request["payload"].get("keep_alive") == "5m" for request in generations)


def unload_requests(ollama) -> list[str]:
    """Запросы «выгрузить модель»: пустой промпт и keep_alive = 0."""
    return [
        request["payload"]["model"]
        for request in ollama.requests
        if request["path"] == "/api/generate"
        and request["payload"].get("keep_alive") == 0
        and not request["payload"].get("prompt")
    ]


def test_models_are_not_kept_in_memory_together(client):
    client.post("/api/reindex")
    # перед индексацией из памяти выгружается модель генерации
    assert unload_requests(client.ollama) == ["qwen3:4b"]

    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})
    # перед генерацией — модель эмбеддингов
    assert unload_requests(client.ollama)[-1] == "bge-m3"

    client.post("/api/search", json={"query": "токен"})
    # перед поиском снова освобождаем память от модели генерации
    assert unload_requests(client.ollama)[-1] == "qwen3:4b"


def test_sequential_models_can_be_switched_off(client):
    config_path = client.tmp_path / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("sequential_models: true", "sequential_models: false"),
        encoding="utf-8",
    )
    client.post("/api/reindex")
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})
    assert unload_requests(client.ollama) == []


def test_status_shows_memory_settings(client):
    config = client.get("/api/status").json()["config"]
    assert config["keep_alive"] == "5m"
    assert config["sequential_models"] is True
    assert config["generation_model"] == "qwen3:4b"


def test_index_stores_vectors_in_sqlite(client):
    client.post("/api/reindex")
    with index_store.connect(client.tmp_path / "index.sqlite3") as connection:
        row = connection.execute("SELECT embedding, text FROM sections LIMIT 1").fetchone()
        tables = {
            name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"documents", "sections", "meta"} <= tables
    assert isinstance(row[0], bytes)  # вектор лежит бинарно, а не текстом
    assert len(index_store.unpack(row[0])) > 10


# --- образцы оформления и обученный формат ---------------------------------


SAMPLE_DOC = """# Настройка вебхуков

## Назначение

Документ описывает подключение вебхуков. Настройка занимает пять минут.

## Предварительные условия

- Роль «Интегратор».
- Открытый порт 443.

## Ограничения

- Не более 5 вебхуков на проект.
"""


def upload_sample(client, name: str = "sample.md", text: str = SAMPLE_DOC):
    return client.post(
        "/api/samples/upload",
        files={"files": (name, text.encode("utf-8"), "text/markdown")},
    )


def test_samples_upload_and_list(client):
    assert client.get("/api/samples").json()["samples"] == []
    response = upload_sample(client)
    assert response.status_code == 200
    assert response.json()["added"] == ["sample.md"]
    assert [item["file"] for item in client.get("/api/samples").json()["samples"]] == ["sample.md"]

    client.request("DELETE", "/api/samples", params={"file": "sample.md"})
    assert client.get("/api/samples").json()["samples"] == []


def test_samples_reject_other_formats(client):
    response = client.post(
        "/api/samples/upload", files={"files": ("sample.pdf", b"x", "application/pdf")}
    )
    assert response.status_code == 400


def test_learning_format_persists_and_is_used_afterwards(client):
    upload_sample(client)
    upload_sample(client, "second.md", SAMPLE_DOC.replace("вебхуков", "уведомлений"))

    learned = client.post("/api/format/learn", json={"use_model": False}).json()
    profile = learned["profile"]
    assert profile["documents"] == 2
    assert profile["address"] == "вы"
    assert profile["bullet_marker"] == "-"
    assert "Назначение" in profile["typical_sections"]
    assert (client.tmp_path / "derived-guide.md").exists()

    # формат запомнен: он подмешивается в каждую следующую генерацию сам
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})
    prompt = last_prompt(client.ollama, "ИСХОДНЫЙ ДОКУМЕНТ")
    assert "Формат, изученный по образцам" in prompt
    assert "Обращение к читателю — на «вы»" in prompt
    assert "Обязательные правила оформления" in prompt  # явный гайд по-прежнему первым


def test_learned_format_can_be_switched_off_and_forgotten(client):
    upload_sample(client)
    client.post("/api/format/learn", json={"use_model": False})

    client.post("/api/format/use", json={"enabled": False})
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})
    assert "Формат, изученный по образцам" not in last_prompt(client.ollama, "ИСХОДНЫЙ ДОКУМЕНТ")

    client.post("/api/format/use", json={"enabled": True})
    sources = client.request("DELETE", "/api/format").json()
    assert sources["derived"]["exists"] is False


def test_learning_format_uses_model_when_asked(client):
    upload_sample(client)
    client.ollama.generate_response = "- Всегда указывать порт\n- Не использовать сокращения"
    learned = client.post("/api/format/learn", json={"use_model": True}).json()
    assert learned["used_model"] is True
    assert "Всегда указывать порт" in learned["text"]
    assert "ИЗМЕРЕННЫЕ ПРИЗНАКИ" in client.ollama.requests[-1]["payload"]["prompt"]


def test_learning_without_samples(client):
    response = client.post("/api/format/learn", json={"use_model": False})
    assert response.status_code == 400
    assert "нет файлов .md" in response.json()["detail"]


def test_several_rule_files_are_all_applied(client):
    response = client.post(
        "/api/style-guides/upload",
        files={"files": ("brand.md", "# Правила бренда\n\n- Название продукта не склоняем.".encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 200
    assert [guide["file"] for guide in response.json()["guides"]] == ["styleguide.md", "brand.md"]

    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"})
    prompt = last_prompt(client.ollama, "ИСХОДНЫЙ ДОКУМЕНТ")
    assert "файл styleguide.md" in prompt
    assert "файл brand.md" in prompt
    assert "Название продукта не склоняем" in prompt

    client.request("DELETE", "/api/style-guides", params={"file": "brand.md"})
    assert [guide["file"] for guide in client.get("/api/style-sources").json()["guides"]] == ["styleguide.md"]


# --- проверка соответствия: формулировка, оформление, шаблон ---------------


BAD_DOC = """## Сначала подраздел

Юзер должен залогиниться. Материал описывает вход.

* пункт не тем маркером
"""


def test_check_endpoint_finds_prose_markup_and_schema_problems(client):
    data = client.post("/api/check", json={"content": BAD_DOC}).json()
    rules = {(item["source"], item["rule"]) for item in data["violations"]}
    assert ("prose", "substitution") in rules            # юзер → пользователь
    assert ("markdown", "first-heading-h1") in rules     # начали с подраздела
    assert ("markdown", "bullet-marker") in rules        # список звёздочкой
    assert ("schema", "missing-section") in rules        # нет обязательных разделов
    assert data["summary"]["errors"] >= 3
    assert data["summary"]["by_source"]["prose"] >= 2


def test_clean_document_passes_checks(client):
    clean = (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")
    data = client.post("/api/check", json={"content": clean}).json()
    errors = [item for item in data["violations"] if item["severity"] == "error"]
    assert errors == [], errors


def test_generation_reports_checks(client):
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    assert "checks" in data
    assert set(data["checks"]) == {"violations", "summary", "fix_iterations"}


def test_generation_fixes_violations_and_keeps_the_better_version(client):
    # модель выдала текст с нарушениями…
    client.ollama.generate_response = BAD_DOC
    # …а на запрос починки вернула чистый вариант
    client.ollama.fix_response = (
        "# Вход в систему\n\n## Назначение\n\nПользователь должен войти.\n\n"
        "## Ограничения\n\n- Одна сессия на пользователя.\n\n"
        "Идентификатор статьи: DOC-0009. Дата обновления: 2026-08-19.\n"
    )
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()

    assert data["checks"]["fix_iterations"] >= 1
    assert "Пользователь должен войти" in data["updated"]
    assert "Юзер" not in data["updated"]
    assert data["checks"]["summary"]["errors"] == 0

    fix_prompt = last_prompt(client.ollama, "НАРУШЕНИЯ, НАЙДЕННЫЕ ПРОВЕРКОЙ")
    assert "Вместо «юзер» пишем «пользователь»" in fix_prompt


def test_generation_keeps_original_answer_if_fix_is_worse(client):
    client.ollama.generate_response = BAD_DOC
    client.ollama.fix_response = "## Ещё хуже\n\n* Юзер\n* Материал\n\nтекст  \n\n\nещё текст"
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()

    assert data["updated"].strip() == BAD_DOC.strip()  # починку отклонили — она не лучше
    assert data["checks"]["summary"]["errors"] > 0     # нарушения показаны, а не спрятаны


def test_fix_loop_can_be_switched_off(client):
    config_path = client.tmp_path / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("max_fix_iterations: 2", "max_fix_iterations: 0"),
        encoding="utf-8",
    )
    client.ollama.generate_response = BAD_DOC
    data = client.post(
        "/api/generate", json={"doc_path": "api-auth.md", "change_description": "правка"}
    ).json()
    assert data["checks"]["fix_iterations"] == 0
    assert data["checks"]["summary"]["errors"] > 0


def test_section_scope_does_not_demand_whole_document_rules(client):
    from backend.checks import run_checks

    config = config_module.load_config()
    section = "## Срок жизни токена\n\nТокен действует 120 минут.\n"
    document_rules = {item.rule for item in run_checks(section, config, scope="document")}
    section_rules = {item.rule for item in run_checks(section, config, scope="section")}
    assert "missing-section" in document_rules
    assert "first-heading-h1" in document_rules
    assert "missing-section" not in section_rules
    assert "first-heading-h1" not in section_rules


def test_stream_also_runs_checks(client):
    with client.stream(
        "POST",
        "/api/generate/stream",
        json={"doc_path": "api-auth.md", "change_description": "правка"},
    ) as response:
        events = [json_module.loads(line) for line in response.iter_lines() if line.strip()]
    assert any(event["type"] == "checking" for event in events)
    assert "checks" in events[-1]


# --- changeset: правки с обоснованием, принимаются поштучно -----------------


def propose(client, description="Срок жизни токена увеличен до 120 минут.", **kwargs):
    body = {"doc_path": "api-auth.md", "change_description": description, **kwargs}
    return client.post("/api/changeset/propose", json=body).json()


def test_changeset_proposes_edits_with_provenance(client):
    client.ollama.generate_response = (
        "## Срок жизни токена\n\nТокен действует 120 минут.\n\n"
        "ОБОСНОВАНИЕ: срок жизни токена увеличен до 120 минут.\nПРЕДПОЛОЖЕНИЕ: нет"
    )
    data = propose(client, section_indexes=[4])

    assert data["summary"]["total"] == 1
    edit = data["edits"][0]
    assert edit["section"].endswith("Срок жизни токена")
    assert "120 минут" in edit["new"]
    assert "ОБОСНОВАНИЕ" not in edit["new"]  # служебные строки убраны из текста
    assert edit["reason"] == "срок жизни токена увеличен до 120 минут."
    assert edit["grounded"] is True
    assert edit["assumption"] is False
    assert edit["confidence"] in {"высокая", "средняя"}
    assert edit["status"] == "pending"


def test_changeset_marks_unjustified_edit_as_assumption(client):
    client.ollama.generate_response = (
        "## Срок жизни токена\n\nТокен действует 120 минут. Добавлена ротация ключей.\n\n"
        "ОБОСНОВАНИЕ: так будет лучше для безопасности\nПРЕДПОЛОЖЕНИЕ: нет"
    )
    data = propose(client, section_indexes=[4])
    edit = data["edits"][0]
    assert edit["grounded"] is False        # цитаты нет в описании изменения
    assert edit["assumption"] is True       # значит это предположение модели
    assert edit["confidence"] == "низкая"
    assert data["summary"]["assumptions"] == 1


def test_changeset_does_not_touch_the_document(client):
    client.ollama.generate_response = "## Срок жизни токена\n\nТокен действует 120 минут."
    propose(client, section_indexes=[4])
    original = (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")
    assert "60 минут" in original


def test_changeset_build_uses_only_accepted_edits(client):
    client.ollama.generate_response = (
        "## Срок жизни токена\n\nТокен действует 120 минут.\n\n"
        "ОБОСНОВАНИЕ: срок жизни токена увеличен до 120 минут.\nПРЕДПОЛОЖЕНИЕ: нет"
    )
    data = propose(client, section_indexes=[4, 5])
    assert len(data["edits"]) >= 1

    first, *rest = data["edits"]
    client.post(
        f"/api/changeset/{data['id']}/decide", json={"edit_id": first["id"], "accepted": True}
    )
    for edit in rest:
        client.post(
            f"/api/changeset/{data['id']}/decide",
            json={"edit_id": edit["id"], "accepted": False, "comment": "не нужно"},
        )

    built = client.post(f"/api/changeset/{data['id']}/build").json()
    assert built["applied_edits"] == 1
    assert "120 минут" in built["updated"]
    # незатронутые разделы остались дословно теми же
    original = built["original"]
    spans_before = outline(original)
    spans_after = outline(built["updated"])
    changed_index = first["section_index"]
    for before, after in zip(spans_before, spans_after):
        if before.start <= spans_before[changed_index].start and before.end >= spans_before[changed_index].end:
            continue
        assert section_text(original, before) == section_text(built["updated"], after)
    assert (client.tmp_path / "output" / built["result_file"]).exists()
    assert "60 минут" in (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")


def test_changeset_build_requires_accepted_edits(client):
    client.ollama.generate_response = "## Срок жизни токена\n\nТокен действует 120 минут."
    data = propose(client, section_indexes=[4])
    response = client.post(f"/api/changeset/{data['id']}/build")
    assert response.status_code == 400
    assert "Ни одна правка не принята" in response.json()["detail"]


def test_rejections_are_logged_and_reused_in_later_prompts(client):
    client.ollama.generate_response = "## Срок жизни токена\n\nТокен действует 120 минут."
    data = propose(client, section_indexes=[4])
    client.post(
        f"/api/changeset/{data['id']}/decide",
        json={"edit_id": data["edits"][0]["id"], "accepted": False, "comment": "не пишем цифры в этом разделе"},
    )

    notes = client.get("/api/feedback", params={"doc_path": "api-auth.md"}).json()["notes"]
    assert notes and notes[-1]["comment"] == "не пишем цифры в этом разделе"

    propose(client, section_indexes=[4])
    prompt = last_prompt(client.ollama, "РАЗДЕЛ, КОТОРЫЙ НУЖНО ОБНОВИТЬ")
    assert "Прошлые правила-исправления от писателя" in prompt
    assert "не пишем цифры в этом разделе" in prompt


def test_changeset_picks_affected_sections_itself(client):
    client.ollama.generate_response = "## Срок жизни токена\n\nТокен действует 120 минут."
    data = propose(client, "срок жизни токена увеличен")
    assert data["edits"], "должна найтись хотя бы одна затронутая секция"
    assert all("Авторизация в API" in edit["section"] for edit in data["edits"])


def test_unknown_changeset(client):
    assert client.get("/api/changeset/нет-такого").status_code == 404


# --- детект расхождений (docs drift) ---------------------------------------


def test_drift_finds_broken_links_and_anchors(client):
    doc = client.tmp_path / "docs" / "api-auth.md"
    doc.write_text(
        doc.read_text(encoding="utf-8")
        + "\n\nСмотрите [экспорт](export-reports.md), [пропажу](нет-файла.md) и "
        "[якорь](#нет-такого-раздела), а также [живой якорь](#ограничения).\n",
        encoding="utf-8",
    )
    data = client.post("/api/drift", json={}).json()
    messages = [item["message"] for item in data["findings"] if item["kind"] == "broken-link"]
    assert any("нет-файла.md" in message for message in messages)
    assert any("нет-такого-раздела" in message for message in messages)
    assert not any("export-reports.md" in message for message in messages)
    assert not any("ограничения" in message.lower() for message in messages)


def test_drift_finds_stale_values(client):
    data = client.post(
        "/api/drift", json={"change_description": "Срок жизни токена увеличен до 120 минут."}
    ).json()
    stale = [item for item in data["findings"] if item["kind"] == "stale-value"]
    assert any("60 минут" in item["excerpt"] for item in stale)
    assert all(item["doc_path"] for item in stale)


def test_drift_finds_mentions_of_removed_things(client):
    data = client.post(
        "/api/drift", json={"change_description": "Убрали `access_token` из ответа."}
    ).json()
    mentions = [item for item in data["findings"] if item["kind"] == "removed-mention"]
    assert mentions and all("access_token" in item["excerpt"] for item in mentions)
    assert data["summary"]["removed_terms"] == ["access_token"]


def test_drift_finds_leftover_markers_and_glossary_terms(client):
    doc = client.tmp_path / "docs" / "install-agent.md"
    doc.write_text(
        doc.read_text(encoding="utf-8") + "\n\nЗдесь [уточнить] и TODO, а юзер должен войти.\n",
        encoding="utf-8",
    )
    data = client.post("/api/drift", json={}).json()
    kinds = {item["kind"] for item in data["findings"] if item["doc_path"] == "install-agent.md"}
    assert "marker" in kinds
    assert "glossary" in kinds


def test_drift_can_be_limited_to_one_document(client):
    data = client.post("/api/drift", json={"doc_path": "api-auth.md"}).json()
    assert all(item["doc_path"] == "api-auth.md" for item in data["findings"])


def test_drift_on_clean_docs_is_quiet(client):
    data = client.post("/api/drift", json={}).json()
    assert data["summary"]["errors"] == 0


# --- карта «что документирует» ---------------------------------------------


def test_document_map_is_built_once_and_used_in_search(client):
    client.post("/api/reindex")
    assert client.get("/api/map").json()["with_summary"] == 0

    built = client.post("/api/map/build").json()
    assert built["built"] == 3
    documents = client.get("/api/map").json()["documents"]
    assert all(item["summary"] for item in documents)
    assert any("Авторизация в API" in item["entities"] for item in documents)

    # повторный вызов ничего не пересчитывает
    assert client.post("/api/map/build").json()["built"] == 0

    candidates = client.post("/api/search", json={"query": "как получить токен доступа"}).json()["candidates"]
    assert candidates[0]["summary"]
    assert candidates[0]["matched_on"] in {"summary", "section"}


def test_summaries_survive_reindex_when_document_is_unchanged(client):
    client.post("/api/reindex")
    client.post("/api/map/build")
    calls_before = len(client.ollama.requests)

    client.post("/api/reindex")
    assert client.get("/api/map").json()["with_summary"] == 3
    assert client.post("/api/map/build").json()["built"] == 0

    # менявшийся документ получает новое резюме
    doc = client.tmp_path / "docs" / "api-auth.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n\nНовый абзац.\n", encoding="utf-8")
    client.post("/api/reindex")
    assert client.get("/api/map").json()["with_summary"] == 2
    assert client.post("/api/map/build").json()["built"] == 1
    assert len(client.ollama.requests) > calls_before


def test_map_requires_index(client):
    response = client.post("/api/map/build")
    assert response.status_code == 400
    assert "не прочитаны" in response.json()["detail"]


def test_golden_cases_pass(tmp_path):
    """Регресс-проверка: golden-прогон должен проходить целиком."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "tests.golden_run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "провалено: 0" in result.stdout


# --- мультипродуктовость: контексты изолированы -----------------------------


def add_second_product(client) -> None:
    """Второй продукт со своими документами, гайдом и индексом."""
    other_docs = client.tmp_path / "beta-docs"
    other_docs.mkdir()
    (other_docs / "beta-api.md").write_text(
        "# Бета API\n\n## Назначение\n\nДокумент описывает бета-интерфейс.\n\n"
        "## Ограничения\n\n- Только для внутренних команд.\n",
        encoding="utf-8",
    )
    (client.tmp_path / "beta-guide.md").write_text(
        "# Гайд беты\n\n- В бете допускаются черновые формулировки.\n", encoding="utf-8"
    )

    raw = yaml.safe_load((client.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["products"] = {
        "default": "core",
        "items": {
            "core": {"name": "Основной продукт"},
            "beta": {
                "name": "Бета",
                "docs_dir": str(other_docs),
                "style_guides": [str(client.tmp_path / "beta-guide.md")],
                "style_guide": str(client.tmp_path / "beta-guide.md"),
                "index_file": str(client.tmp_path / "beta-index.sqlite3"),
                "output_dir": str(client.tmp_path / "beta-output"),
                "derived_guide": str(client.tmp_path / "beta-derived.md"),
                "samples_dir": str(client.tmp_path / "beta-samples"),
            },
        },
    }
    (client.tmp_path / "config.yaml").write_text(
        yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8"
    )


def test_products_are_listed(client):
    add_second_product(client)
    data = client.get("/api/products").json()
    assert data["default"] == "core"
    assert {item["id"] for item in data["products"]} == {"core", "beta"}
    beta = next(item for item in data["products"] if item["id"] == "beta")
    assert beta["documents"] == 1
    assert beta["style_guides"] == ["beta-guide.md"]


def test_search_does_not_cross_products(client):
    add_second_product(client)
    client.post("/api/reindex")
    client.post("/api/reindex", params={"product": "beta"})

    core = client.post("/api/search", json={"query": "токен доступа"}).json()["candidates"]
    beta = client.post("/api/search", json={"query": "токен доступа"}, params={"product": "beta"}).json()["candidates"]

    assert {item["path"] for item in core} == {"api-auth.md", "export-reports.md", "install-agent.md"}
    assert {item["path"] for item in beta} == {"beta-api.md"}


def test_each_product_has_its_own_rules(client):
    add_second_product(client)
    client.post(
        "/api/generate",
        json={"doc_path": "beta-api.md", "change_description": "правка"},
        params={"product": "beta"},
    )
    prompt = last_prompt(client.ollama, "ИСХОДНЫЙ ДОКУМЕНТ")
    assert "Гайд беты" in prompt
    assert "Гайд по стилю технической документации" not in prompt


def test_documents_of_another_product_are_not_reachable(client):
    add_second_product(client)
    response = client.get("/api/document", params={"path": "api-auth.md", "product": "beta"})
    assert response.status_code == 404


def test_unknown_product_is_reported(client):
    response = client.get("/api/status", params={"product": "нет-такого"})
    assert response.status_code == 404
    assert "не настроен" in response.json()["detail"]


def test_product_settings_do_not_leak_into_common(client):
    add_second_product(client)
    client.post("/api/config", json={"generation_model": "qwen3:8b"}, params={"product": "beta"})

    raw = yaml.safe_load((client.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert raw["products"]["items"]["beta"]["ollama"]["generation_model"] == "qwen3:8b"
    assert raw["ollama"]["generation_model"] == "qwen3:4b"
    assert client.get("/api/status").json()["config"]["generation_model"] == "qwen3:4b"
    assert client.get("/api/status", params={"product": "beta"}).json()["config"]["generation_model"] == "qwen3:8b"


# --- новая статья по шаблону -----------------------------------------------


def test_new_article_follows_the_template(client):
    data = client.post(
        "/api/article/new",
        json={"title": "Настройка вебхуков", "requirements": "Вебхуки шлют POST на адрес клиента."},
    ).json()

    assert data["sections"] == ["Назначение", "Ограничения", "Предварительные условия"]
    text = data["text"]
    # черновик сразу получает блок метаданных своего типа и профиля
    assert text.startswith("---")
    assert f"type_id: {data['type_id']}" in text
    assert "article_id: [уточнить]" in text
    assert "# Настройка вебхуков" in text
    for section in ("## Назначение", "## Ограничения", "## Предварительные условия"):
        assert section in text
    assert "[уточнить]" in text  # где данных не хватило — пометка, а не выдумка
    assert data["checks"]["summary"]["errors"] == 0
    assert (client.tmp_path / "output" / data["result_file"]).read_text(encoding="utf-8") == text


def test_new_article_uses_existing_docs_only_as_tone_example(client):
    client.post("/api/reindex")
    client.post(
        "/api/article/new",
        json={"title": "Новая статья", "requirements": "Требования к функционалу."},
    )
    prompt = last_prompt(client.ollama, "Напиши раздел")
    assert "только манера изложения, факты не копировать" in prompt


def test_new_article_can_skip_examples(client):
    data = client.post(
        "/api/article/new",
        json={"title": "Без примера", "requirements": "Требования.", "use_examples": False},
    ).json()
    assert data["example_from"] == ""


def test_new_article_is_checked_and_fixed(client):
    client.ollama.generate_response = "## Назначение\n\nЮзер должен залогиниться."
    client.ollama.fix_response = "## Назначение\n\nПользователь должен войти."
    data = client.post(
        "/api/article/new",
        json={"title": "Статья", "requirements": "Требования.", "use_examples": False},
    ).json()
    assert data["checks"]["fix_iterations"] >= 1
    assert "Юзер" not in data["text"]


# --- автосвязывание по многим статьям --------------------------------------


def test_impact_lists_all_affected_documents(client):
    client.post("/api/reindex")
    client.post("/api/map/build")

    data = client.post(
        "/api/impact", json={"change_description": "Токен теперь живёт 120 минут, экспорт отчётов не менялся."}
    ).json()

    assert data["summary"]["total"] >= 1
    assert data["summary"]["considered"] >= 1
    first = data["documents"][0]
    assert first["action"] in {"дополнить", "заменить", "устарело"}
    assert first["reason"]
    assert first["relevance"] >= 45
    # отсортировано по убыванию релевантности
    assert data["documents"] == sorted(data["documents"], key=lambda item: -item["relevance"])


def test_impact_classification_comes_from_the_model(client):
    client.post("/api/reindex")
    client.ollama.impact_response = "КЛАСС: устарело\nПРИЧИНА: функциональность удалена"
    data = client.post("/api/impact", json={"change_description": "Удалили выгрузку отчётов"}).json()
    assert all(item["action"] == "устарело" for item in data["documents"])
    assert data["summary"]["by_action"] == {"устарело": len(data["documents"])}


def test_impact_requires_index(client):
    response = client.post("/api/impact", json={"change_description": "что-то"})
    assert response.status_code == 400


def test_impact_respects_product_isolation(client):
    add_second_product(client)
    client.post("/api/reindex", params={"product": "beta"})
    data = client.post(
        "/api/impact",
        json={"change_description": "изменение в бете"},
        params={"product": "beta"},
    ).json()
    assert all(item["path"] == "beta-api.md" for item in data["documents"])


# --- мультиязычность: каскад на языковые версии -----------------------------


def test_language_versions_are_listed(client):
    data = client.get("/api/languages", params={"doc_path": "api-auth.md"}).json()
    assert data["source"] == "ru"
    assert data["targets"] == ["en", "kk"]
    languages = {item["language"]: item for item in data["versions"]}
    assert languages["ru"]["is_source"] is True
    assert languages["kk"]["needs_review"] is True   # низкоресурсный язык
    assert languages["en"]["needs_review"] is False
    assert languages["en"]["path"].endswith("/en/api-auth.md")


def test_cascade_translates_and_marks_versions_needing_review(client):
    data = client.post("/api/cascade", json={"doc_path": "api-auth.md"}).json()

    assert data["summary"]["translated"] == 2
    versions = {item["language"]: item for item in data["results"]}
    assert "<!-- en -->" in versions["en"]["text"]
    assert versions["en"]["needs_review"] is False
    assert versions["kk"]["needs_review"] is True
    assert "ручная вычитка" in versions["kk"]["reason"]

    # результаты сохранены отдельными файлами, оригинал не тронут
    for item in data["results"]:
        assert (client.tmp_path / "output" / item["file"]).exists()
    assert "60 минут" in (client.tmp_path / "docs" / "api-auth.md").read_text(encoding="utf-8")


def test_cascade_passes_glossary_to_the_model(client):
    client.post("/api/cascade", json={"doc_path": "api-auth.md", "targets": ["en"]})
    prompt = last_prompt(client.ollama, "Переведи документ на язык")
    assert "ГЛОССАРИЙ" in prompt
    assert "токен доступа → access token" in prompt


def test_cascade_checks_each_language_version(client):
    client.ollama.translate_response = "## Сначала подраздел\n\nЮзер должен залогиниться."
    data = client.post("/api/cascade", json={"doc_path": "api-auth.md", "targets": ["en"]}).json()
    version = data["results"][0]
    assert version["checks"]["errors"] > 0
    assert version["needs_review"] is True
    assert "нарушения" in version["reason"]


def test_cascade_without_targets(client):
    config_path = client.tmp_path / "config.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["languages"]["targets"] = []
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    response = client.post("/api/cascade", json={"doc_path": "api-auth.md"})
    assert response.status_code == 400
    assert "целевые языки" in response.json()["detail"]


def test_cascade_of_unknown_document(client):
    response = client.post("/api/cascade", json={"doc_path": "нет-такого.md"})
    assert response.status_code == 404


# --- конфиденциальность, роли и аудит ---------------------------------------


def make_secret_doc(client) -> None:
    secret_dir = client.tmp_path / "docs" / "secret"
    secret_dir.mkdir(exist_ok=True)
    (secret_dir / "roadmap.md").write_text(
        "---\nclassification: confidential\n---\n\n# Планы по токенам\n\n"
        "## Назначение\n\nДокумент описывает будущий механизм токенов.\n\n"
        "## Ограничения\n\n- Только для руководителей.\n",
        encoding="utf-8",
    )


def enable_rutoken(client, thumbprint: str = "AB12CD34", role: str = "lead") -> None:
    raw = yaml.safe_load((client.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["security"]["auth"] = "rutoken"
    raw["security"]["tokens"] = {thumbprint: role}
    (client.tmp_path / "config.yaml").write_text(
        yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8"
    )


def test_search_hides_documents_the_role_may_not_see(client):
    make_secret_doc(client)
    client.post("/api/reindex")

    candidates = client.post("/api/search", json={"query": "механизм токенов"}).json()["candidates"]
    paths = {item["path"] for item in candidates}
    assert "secret/roadmap.md" not in paths          # роль writer конфиденциальное не видит
    assert all(item["classification"] in {"public", "internal"} for item in candidates)


def test_role_with_clearance_sees_confidential_documents(client):
    make_secret_doc(client)
    enable_rutoken(client, "AB12CD34", "lead")
    client.post("/api/reindex", headers={"X-Rutoken-Thumbprint": "AB12CD34"})

    candidates = client.post(
        "/api/search",
        json={"query": "механизм токенов"},
        headers={"X-Rutoken-Thumbprint": "AB12CD34"},
    ).json()["candidates"]
    assert "secret/roadmap.md" in {item["path"] for item in candidates}


def test_rutoken_is_required_when_enabled(client):
    enable_rutoken(client)
    response = client.post("/api/search", json={"query": "токен"})
    assert response.status_code == 401
    assert "аппаратный токен" in response.json()["detail"]

    wrong = client.post(
        "/api/search", json={"query": "токен"}, headers={"X-Rutoken-Thumbprint": "UNKNOWN99"}
    )
    assert wrong.status_code == 401
    assert "не входит в список" in wrong.json()["detail"]


def test_role_can_be_limited_to_products(client):
    add_second_product(client)
    enable_rutoken(client, "CORE1", "core_writer")
    raw = yaml.safe_load((client.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["security"]["roles"]["core_writer"] = {"classifications": ["internal"], "products": ["core"]}
    (client.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    headers = {"X-Rutoken-Thumbprint": "CORE1"}
    assert client.post("/api/search", json={"query": "токен"}, headers=headers).status_code in (200, 400)
    denied = client.post(
        "/api/search", json={"query": "токен"}, params={"product": "beta"}, headers=headers
    )
    assert denied.status_code == 403
    assert "не имеет доступа к продукту" in denied.json()["detail"]


def test_audit_logs_events_without_content(client):
    client.post("/api/generate", json={"doc_path": "api-auth.md", "change_description": "секретная правка"})
    records = client.get("/api/audit").json()["records"]
    assert records
    event = records[-1]
    assert event["event"] == "generate"
    assert event["model"] == "qwen3:4b"
    assert event["doc"] == "api-auth.md"
    # само описание в журнал не попадает — только отпечаток и длина
    raw_log = (client.tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "секретная правка" not in raw_log
    assert "description_fingerprint" in raw_log


def test_outbound_check_blocks_requirements_and_confidential(client):
    from backend import security

    config = config_module.load_config()
    plain = security.check_outbound(config, "# Документ\n\nОбычный текст.", "api-auth.md")
    assert plain["allowed"] is True

    secret = security.check_outbound(
        config, "---\nclassification: confidential\n---\n\n# Планы\n", "secret/roadmap.md"
    )
    assert secret["allowed"] is False
    assert "конфиденциальный" in secret["reasons"][0]

    with_requirements = security.check_outbound(
        config, "# Документ\n\nЗдесь описаны функциональные требования к модулю.", "api-auth.md"
    )
    assert with_requirements["allowed"] is False
    assert "функциональных требований" in with_requirements["reasons"][0]


# --- публикация: только по подтверждению, идемпотентно ----------------------


@pytest.fixture()
def targets():
    from tests.fake_targets import FakeTargets

    server = FakeTargets().start()
    yield server
    server.stop()


def enable_publishing(client, targets, monkeypatch=None) -> None:
    raw = yaml.safe_load((client.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["publish"] = {
        "enabled": True,
        "confluence": {"base_url": targets.url, "space": "DOCS", "auth_env": "TEST_CONFLUENCE_TOKEN"},
        "portal": {"base_url": targets.url, "auth_env": "TEST_PORTAL_TOKEN"},
        "registry": str(client.tmp_path / "publications.json"),
    }
    (client.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def test_publish_preview_shows_targets_and_does_not_send(client, targets):
    enable_publishing(client, targets)
    data = client.post("/api/publish/preview", json={"doc_path": "api-auth.md"}).json()

    assert data["enabled"] is True
    assert {item["target"] for item in data["targets"]} == {"confluence", "portal"}
    assert all(item["action"] == "создать" for item in data["targets"])
    assert data["outbound"]["allowed"] is True
    assert data["title"] == "Авторизация в API"
    assert targets.requests == []  # превью ничего не отправляет


def test_publish_requires_confirmation(client, targets):
    enable_publishing(client, targets)
    response = client.post("/api/publish", json={"doc_path": "api-auth.md"})
    assert response.status_code == 400
    assert "не подтверждена" in response.json()["detail"]
    assert targets.requests == []


def test_publish_sends_to_both_targets_and_is_idempotent(client, targets):
    enable_publishing(client, targets)

    first = client.post("/api/publish", json={"doc_path": "api-auth.md", "confirm": True}).json()
    assert first["summary"]["published"] == 2
    assert {item["action"] for item in first["results"]} == {"создано"}
    assert len(targets.pages) == 1 and len(targets.articles) == 1

    second = client.post("/api/publish", json={"doc_path": "api-auth.md", "confirm": True}).json()
    assert second["summary"]["published"] == 2
    assert {item["action"] for item in second["results"]} == {"обновлено"}
    # дубликатов не появилось: те же страница и статья, версии выросли
    assert len(targets.pages) == 1 and len(targets.articles) == 1
    assert second["registry"]["confluence"]["id"] == first["registry"]["confluence"]["id"]

    stored = client.get("/api/publications").json()["publications"]
    assert stored["api-auth.md"]["portal"]["id"] == first["registry"]["portal"]["id"]


def test_publish_is_blocked_for_confidential_documents(client, targets):
    make_secret_doc(client)
    enable_publishing(client, targets)
    response = client.post(
        "/api/publish", json={"doc_path": "secret/roadmap.md", "confirm": True}
    )
    assert response.status_code == 400
    assert "конфиденциальный" in response.json()["detail"]
    assert targets.requests == []


def test_publish_is_blocked_when_text_contains_requirements(client, targets):
    doc = client.tmp_path / "docs" / "install-agent.md"
    doc.write_text(
        doc.read_text(encoding="utf-8") + "\n\nЗдесь описаны функциональные требования к агенту.\n",
        encoding="utf-8",
    )
    enable_publishing(client, targets)
    response = client.post("/api/publish", json={"doc_path": "install-agent.md", "confirm": True})
    assert response.status_code == 400
    assert "функциональных требований" in response.json()["detail"]
    assert targets.requests == []


def test_publish_is_off_by_default(client):
    response = client.post("/api/publish", json={"doc_path": "api-auth.md", "confirm": True})
    assert response.status_code == 400
    assert "выключена" in response.json()["detail"]


def test_publish_uses_token_from_environment(client, targets, monkeypatch):
    enable_publishing(client, targets)
    monkeypatch.setenv("TEST_CONFLUENCE_TOKEN", "secret-token")
    client.post("/api/publish", json={"doc_path": "api-auth.md", "targets": ["confluence"], "confirm": True})
    assert targets.requests[-1]["auth"] == "Bearer secret-token"


def test_publication_events_are_audited_without_text(client, targets):
    enable_publishing(client, targets)
    client.post("/api/publish", json={"doc_path": "api-auth.md", "confirm": True})
    records = client.get("/api/audit").json()["records"]
    event = [item for item in records if item["event"] == "publish"][-1]
    assert event["doc"] == "api-auth.md"
    assert sorted(event["targets"]) == ["confluence", "portal"]
    assert "Токен действует" not in (client.tmp_path / "audit.jsonl").read_text(encoding="utf-8")


# --- docs-config: профили, типы статей, KDOC-правила ------------------------


def fixture(name: str) -> str:
    return (REPO_ROOT / "tests" / "fixtures" / f"{name}.md").read_text(encoding="utf-8")


def describe(text: str) -> dict:
    from backend.checks import describe_document

    return describe_document(text, config_module.load_config())


def check_text(text: str):
    from backend.checks import run_checks

    return run_checks(text, config_module.load_config())


def test_docs_config_is_the_source_of_truth(client):
    data = client.get("/api/docs-config").json()
    assert data["files"]["schemas"]["present"] is True
    assert len(data["types"]) == 10                     # десять типов статей из разбора
    assert set(data["profiles"]) == {"legacy_help", "modern_help", "modern_kb"}
    assert data["admonition_types"] == ["note", "warning", "important", "example"]
    assert {rule["id"] for rule in data["kdoc"]} >= {
        "KDOC-ADMONITION-TYPE", "KDOC-LEADIN", "KDOC-RESULT", "KDOC-UI-BOLD",
        "KDOC-TABLE-FOR-PARALLEL", "KDOC-FOOTER-META", "KDOC-ABBR-EXPANSION",
        "KDOC-IMAGE-ALT", "KDOC-CROSSLOCALE",
    }
    assert "MD013" in data["markdownlint_codes"]
    assert data["glossary"]["terms"] > 0
    assert "KUMA" in data["glossary"]["do_not_translate"]
    assert data["errors"] == []


def test_profile_from_front_matter_and_heuristics():
    assert describe(fixture("howto_modern_help"))["profile"] == "modern_help"

    legacy = describe(fixture("howto_legacy_help"))
    assert legacy["profile"] == "legacy_help"
    assert "подвал" in legacy["profile_source"]

    kb = describe(fixture("troubleshooting_modern_kb"))
    assert kb["profile"] == "modern_kb"


def test_article_type_detected_from_structure():
    # убираем front-matter целиком: тип должен определиться по структуре документа
    text = fixture("troubleshooting_modern_kb").split("---\n", 2)[2].lstrip()
    detected = describe(text)
    assert detected["type_id"] == "troubleshooting"
    assert "эвристика" in detected["type_source"]


def test_type_schema_checks_sections_order_and_meta():
    broken = (
        "---\ntype_id: troubleshooting\ntemplate_profile: modern_kb\n---\n\n"
        "# Ошибка\n\n## Решение\n\nТекст.\n\n## Симптомы\n\nТекст.\n"
    )
    rules = {(item.rule, item.excerpt) for item in check_text(broken)}
    assert ("missing-section", "Причина") in rules          # нет обязательного раздела
    assert any(rule == "section-order" for rule, _ in rules)  # порядок нарушен
    assert ("missing-meta", "article_id") in rules            # нет метаполя профиля
    assert ("missing-meta", "kb_id") in rules


def test_profile_rules_do_not_leak_between_generations():
    # У старого профиля метаданные лежат в подвале, и правило footer-meta к нему не применяется
    legacy_rules = {item.rule for item in check_text(fixture("howto_legacy_help"))}
    assert "KDOC-FOOTER-META" not in legacy_rules

    modern_without_footer = fixture("howto_modern_help").replace(
        "*Идентификатор статьи: KB-1001. Дата обновления: 2026-08-19.*", ""
    ).replace("updated: 2026-08-19\n", "")
    modern_rules = {item.rule for item in check_text(modern_without_footer)}
    assert "KDOC-FOOTER-META" in modern_rules


def test_kdoc_rules_fire_only_for_their_type():
    howto = {item.rule for item in check_text(fixture("howto_modern_help"))}
    assert "KDOC-ESCALATION" not in howto      # правило только для troubleshooting

    без_эскалации = fixture("troubleshooting_modern_kb").replace(
        "## Эскалация\n\nЕсли решение не помогло, обратитесь в техническую поддержку.\n\n", ""
    )
    assert "KDOC-ESCALATION" in {item.rule for item in check_text(без_эскалации)}


def test_clean_fixtures_pass_all_checks():
    for name in ("howto_modern_help", "troubleshooting_modern_kb"):
        problems = [item for item in check_text(fixture(name)) if item.severity == "error"]
        assert problems == [], f"{name}: {[item.message for item in problems]}"


def test_bad_howto_triggers_expected_kdoc_rules():
    found = {item.rule for item in check_text(fixture("bad_howto"))}
    assert "KDOC-LEADIN" in found              # нет лид-ина «Чтобы …:»
    assert "KDOC-RESULT" in found              # нет абзаца-результата
    assert "KDOC-UI-BOLD" in found             # UI-метка в кавычках вместо полужирного
    assert "KDOC-ADMONITION-TYPE" in found     # врезка без машиночитаемого типа
    assert "KDOC-TABLE-FOR-PARALLEL" in found  # три однотипных пункта
    assert "KDOC-IMAGE-ALT" in found           # нет alt-текста


def test_admonition_type_never_comes_from_colour():
    coloured = [
        item for item in check_text(fixture("bad_howto"))
        if item.rule == "KDOC-ADMONITION-TYPE" and "цвет" in item.message
    ]
    assert coloured, "цветовая врезка должна считаться нарушением"


def test_disputed_rules_are_recommendations_not_violations():
    items = {item.rule: item for item in check_text(fixture("bad_howto"))}
    assert items["KDOC-TABLE-FOR-PARALLEL"].kind == "recommendation"
    assert items["KDOC-RESULT"].kind == "recommendation"
    assert items["KDOC-LEADIN"].kind == "violation"
    assert items["KDOC-UI-BOLD"].kind == "violation"


def test_disputed_rule_can_be_raised_to_error(client):
    config_path = client.tmp_path / "config.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["checks"]["kdoc"] = {"KDOC-TABLE-FOR-PARALLEL": "error"}
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    data = client.post("/api/check", json={"content": fixture("bad_howto")}).json()
    table = [item for item in data["violations"] if item["rule"] == "KDOC-TABLE-FOR-PARALLEL"]
    assert table and table[0]["severity"] == "error"
    assert table[0]["kind"] == "violation"


def test_external_api_reference_is_not_linted():
    found = check_text(fixture("api_reference_external"))
    assert len(found) == 1
    assert found[0].rule == "not-lintable"
    assert found[0].kind == "recommendation"
    assert "Swagger" in found[0].message or "swagger" in found[0].message.lower()


def test_check_endpoint_reports_profile_and_type(client):
    data = client.post("/api/check", json={"content": fixture("howto_modern_help")}).json()
    assert data["document"]["profile"] == "modern_help"
    assert data["document"]["type_id"] == "howto_procedure"
    assert data["summary"]["violations"] == 0
    assert "recommendations" in data["summary"]


# --- глоссарий в словарь Vale и кросс-локальная сверка ----------------------


def test_glossary_becomes_vale_vocabulary(client):
    data = client.post("/api/docs-config/sync-glossary").json()
    assert data["ok"] is True
    assert data["accepted"] > 0 and data["rejected"] > 0
    assert "KUMA" in data["do_not_translate"]

    written = {Path(item).name: Path(item) for item in data["written"]}
    accept = written["accept.txt"].read_text(encoding="utf-8")
    reject = written["reject.txt"].read_text(encoding="utf-8")
    substitutions = yaml.safe_load(written["GlossarySubstitutions.yml"].read_text(encoding="utf-8"))

    assert "KUMA" in accept and "эндпоинт" in accept
    assert "эндпойнт" in reject                      # так писать нельзя
    assert substitutions["swap"]["эндпойнт"] == "эндпоинт"
    assert substitutions["extends"] == "substitution"


def test_do_not_translate_terms_are_kept_out_of_translation_pairs(client):
    from backend import glossary_sync

    config = config_module.load_config()
    pairs = glossary_sync.translation_pairs(config, "en")
    assert "KUMA" not in pairs                       # продуктовое имя не переводим
    assert pairs.get("токен доступа") == "access token"
    assert "KUMA" in glossary_sync.keep_as_is(config)


def make_locale_versions(client, *, same_structure=True, same_date=True) -> None:
    """Русская и английская версии одной статьи (article_id совпадает)."""
    docs = client.tmp_path / "docs"
    (docs / "ru").mkdir(parents=True, exist_ok=True)
    (docs / "en").mkdir(parents=True, exist_ok=True)

    (docs / "ru" / "webhooks.md").write_text(
        "# Вебхуки\n\n## Назначение\n\nТекст.\n\n## Ограничения\n\n- Пять вебхуков.\n\n"
        "Идентификатор статьи: DOC-7001. Дата обновления: 2026-08-19.\n",
        encoding="utf-8",
    )
    english = "# Webhooks\n\n## Purpose\n\nText.\n"
    if same_structure:
        english += "\n## Limitations\n\n- Five webhooks.\n"
    english += (
        "\nArticle ID: DOC-7001. Last updated: "
        + ("2026-08-19" if same_date else "2026-07-01")
        + ".\n"
    )
    (docs / "en" / "webhooks.md").write_text(english, encoding="utf-8")


def test_crosslocale_checks_structure_and_dates_separately(client):
    make_locale_versions(client, same_structure=True, same_date=False)
    data = client.get("/api/crosslocale").json()

    article = next(item for item in data["articles"] if item["article_id"] == "DOC-7001")
    assert article["languages"] == ["en", "ru"]
    assert article["structure_equal"] is True        # структура совпала…
    assert article["dates_equal"] is False           # …но обновляли версии в разное время
    kinds = {item["kind"] for item in data["findings"] if item["article_id"] == "DOC-7001"}
    assert kinds == {"date-mismatch"}


def test_crosslocale_finds_structure_mismatch(client):
    make_locale_versions(client, same_structure=False, same_date=True)
    data = client.get("/api/crosslocale").json()
    kinds = {item["kind"] for item in data["findings"] if item["article_id"] == "DOC-7001"}
    assert "structure-mismatch" in kinds
    assert "date-mismatch" not in kinds              # даты совпадают — про них молчим


def test_missing_locale_is_reported_only_when_required(client):
    make_locale_versions(client)
    assert not [item for item in client.get("/api/crosslocale").json()["findings"]
                if item["kind"] == "missing-locale"]

    config_path = client.tmp_path / "config.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["languages"]["require_all_targets"] = True
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    missing = [item for item in client.get("/api/crosslocale").json()["findings"]
               if item["kind"] == "missing-locale"]
    assert missing and "kk" in missing[0]["message"]


def test_crosslocale_findings_appear_in_drift(client):
    make_locale_versions(client, same_structure=False, same_date=False)
    data = client.post("/api/drift", json={}).json()
    kinds = set(data["summary"]["by_kind"])
    assert "structure-mismatch" in kinds
    assert "date-mismatch" in kinds


# --- импорт справки по ссылке ----------------------------------------------


@pytest.fixture()
def portal():
    from tests.fake_portal import FakePortal

    server = FakePortal().start()
    yield server
    server.stop()


def allow_import(client, portal, enabled: bool = True, hosts: list[str] | None = None) -> None:
    raw = yaml.safe_load((client.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["import_web"] = {
        "enabled": enabled,
        "allowed_hosts": hosts if hosts is not None else ["127.0.0.1"],
        "timeout": 10,
        "user_agent": "docs-updater/test",
    }
    (client.tmp_path / "config.yaml").write_text(
        yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8"
    )


def test_import_is_off_by_default(client, portal):
    response = client.post("/api/import/preview", json={"url": f"{portal.url}/help/webhooks"})
    assert response.status_code == 400
    assert "выключен" in response.json()["detail"]
    assert portal.requests == []          # ничего не запрашивали


def test_import_requires_allowed_host(client, portal):
    allow_import(client, portal, hosts=["help.internal"])
    response = client.post("/api/import/preview", json={"url": f"{portal.url}/help/webhooks"})
    assert response.status_code == 400
    assert "не в списке разрешённых" in response.json()["detail"]
    assert portal.requests == []


def test_import_preview_converts_page_to_markdown(client, portal):
    allow_import(client, portal)
    data = client.post("/api/import/preview", json={"url": f"{portal.url}/help/webhooks"}).json()

    markdown = data["markdown"]
    assert data["title"] == "Настройка вебхуков"
    assert data["meta"]["article_id"] == "KB-9001"
    assert data["meta"]["updated"] == "2026-08-19"

    assert markdown.startswith("# Настройка вебхуков")
    assert "## Порядок действий" in markdown
    assert "1. Откройте раздел **Настройки**." in markdown        # список и полужирный
    assert "> [!WARNING]" in markdown                              # врезка по классу, не по цвету
    assert "| Параметр | Описание |" in markdown                   # таблица
    assert "```\ncurl -X POST http://localhost/hook\n```" in markdown
    assert "![Схема вебхука](" in markdown                         # alt-текст сохранён
    assert "Навигация" not in markdown and "Подвал сайта" not in markdown
    assert f"[разделом про лимиты]({portal.url}/limits)" in markdown or "лимиты" in markdown

    assert portal.requests == ["/help/webhooks"]
    # превью ничего не сохраняет
    assert client.get("/api/samples").json()["samples"] == []


def test_imported_page_can_become_a_sample_or_a_document(client, portal):
    allow_import(client, portal)

    sample = client.post(
        "/api/import/url", json={"url": f"{portal.url}/help/webhooks", "target": "samples"}
    ).json()
    assert sample["saved_to"] == "samples"
    assert (client.tmp_path / "samples" / sample["file"]).exists()
    assert [item["file"] for item in client.get("/api/samples").json()["samples"]] == [sample["file"]]

    document = client.post(
        "/api/import/url",
        json={"url": f"{portal.url}/help/webhooks", "target": "docs", "file_name": "webhooks"},
    ).json()
    assert document["file"] == "webhooks.md"
    assert (client.tmp_path / "docs" / "webhooks.md").exists()


def test_imported_page_can_be_used_to_learn_the_format(client, portal):
    allow_import(client, portal)
    client.post("/api/import/url", json={"url": f"{portal.url}/help/webhooks"})
    learned = client.post("/api/format/learn", json={"use_model": False}).json()
    assert learned["profile"]["documents"] == 1
    assert "Порядок действий" in " ".join(learned["profile"]["typical_sections"]) or learned["text"]


def test_import_is_audited_without_page_text(client, portal):
    allow_import(client, portal)
    client.post("/api/import/preview", json={"url": f"{portal.url}/help/webhooks"})
    records = client.get("/api/audit").json()["records"]
    event = [item for item in records if item["event"] == "import"][-1]
    assert event["url"].endswith("/help/webhooks")
    assert event["chars"] > 0
    assert "вебхук" not in (client.tmp_path / "audit.jsonl").read_text(encoding="utf-8").lower()


def test_import_reports_unreachable_page(client, portal):
    allow_import(client, portal)
    response = client.post("/api/import/preview", json={"url": f"{portal.url}/missing"})
    assert response.status_code == 400
    assert "Не удалось получить страницу" in response.json()["detail"]


def test_readiness_check_runs_and_reports(tmp_path):
    """Проверялка готовности запускается и печатает разделы, ничего не меняя."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "check.py"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "Что нужно, чтобы сервис вообще запустился" in output
    assert "Python" in output
    # Проверялка только смотрит: подсказки к невыполненным пунктам должны быть командами.
    if "✗" in output:
        assert "ollama" in output.lower() or "install_ui" in output or "pip install" in output
