"""FastAPI-приложение локального сервиса обновления документации.

Никаких внешних сетевых обращений: только localhost:11434 (Ollama).
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import indexer, search
from .config import load_config, resolve_path, save_config
from .diffing import build_diff, unified_diff
from .generator import generate_update
from .ollama_client import OllamaClient, OllamaError

app = FastAPI(title="Локальный сервис обновления документации", version="1.0.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# --- вспомогательное -------------------------------------------------------


def get_client(config: dict[str, Any]) -> OllamaClient:
    return OllamaClient(
        host=config["ollama"]["host"],
        timeout=float(config["ollama"]["request_timeout"]),
    )


def safe_join(base: Path, relative: str) -> Path:
    """Защита от выхода за пределы рабочей папки (../)."""
    candidate = (base / relative).resolve()
    base_resolved = base.resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise HTTPException(status_code=400, detail="Недопустимый путь к файлу.")
    return candidate


def read_style_guide(config: dict[str, Any]) -> str:
    path = resolve_path(config["paths"]["style_guide"])
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def slugify(value: str) -> str:
    return re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("_") or "document"


@app.exception_handler(OllamaError)
async def ollama_error_handler(_request, exc: OllamaError) -> JSONResponse:
    return JSONResponse(status_code=503, content=exc.as_dict())


# --- модели запросов -------------------------------------------------------


class ConfigPatch(BaseModel):
    docs_dir: str | None = None
    style_guide: str | None = None
    generation_model: str | None = None
    embedding_model: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = None


class GenerateRequest(BaseModel):
    doc_path: str
    change_description: str = Field(min_length=1)


class ApplyRequest(BaseModel):
    doc_path: str
    result_path: str


class StyleGuideText(BaseModel):
    content: str


# --- статус и конфигурация -------------------------------------------------


@app.get("/api/status")
def status() -> dict[str, Any]:
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    guide_path = resolve_path(config["paths"]["style_guide"])
    index = indexer.load_index(config)

    ollama: dict[str, Any] = {"host": config["ollama"]["host"]}
    try:
        installed = get_client(config).list_models()
        ollama["available"] = True
        ollama["models"] = installed
        for key, model in (
            ("generation_model", config["ollama"]["generation_model"]),
            ("embedding_model", config["ollama"]["embedding_model"]),
        ):
            base = model.split(":")[0]
            ollama[f"{key}_installed"] = any(name == model or name.split(":")[0] == base for name in installed)
    except OllamaError as exc:
        ollama.update({"available": False, "models": [], **exc.as_dict()})

    return {
        "config": {
            "docs_dir": str(docs_dir),
            "docs_dir_raw": config["paths"]["docs_dir"],
            "docs_dir_exists": docs_dir.exists(),
            "style_guide": str(guide_path),
            "style_guide_raw": config["paths"]["style_guide"],
            "style_guide_exists": guide_path.exists(),
            "generation_model": config["ollama"]["generation_model"],
            "embedding_model": config["ollama"]["embedding_model"],
            "top_k": config["search"]["top_k"],
        },
        "markdown_files": len(indexer.find_markdown_files(docs_dir)),
        "index": indexer.index_summary(index),
        "ollama": ollama,
    }


@app.post("/api/config")
def update_config(patch: ConfigPatch) -> dict[str, Any]:
    config = load_config()
    if patch.docs_dir:
        config["paths"]["docs_dir"] = patch.docs_dir.strip()
    if patch.style_guide:
        config["paths"]["style_guide"] = patch.style_guide.strip()
    if patch.generation_model:
        config["ollama"]["generation_model"] = patch.generation_model.strip()
    if patch.embedding_model:
        config["ollama"]["embedding_model"] = patch.embedding_model.strip()
    save_config(config)
    return status()


# --- гайд по стилю ---------------------------------------------------------


@app.get("/api/style-guide")
def get_style_guide() -> dict[str, Any]:
    config = load_config()
    path = resolve_path(config["paths"]["style_guide"])
    return {"path": str(path), "exists": path.exists(), "content": read_style_guide(config)}


@app.put("/api/style-guide")
def put_style_guide(payload: StyleGuideText) -> dict[str, Any]:
    config = load_config()
    path = resolve_path(config["paths"]["style_guide"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.content, encoding="utf-8")
    return {"path": str(path), "exists": True, "content": payload.content}


@app.post("/api/style-guide/upload")
async def upload_style_guide(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith((".md", ".markdown", ".txt")):
        raise HTTPException(status_code=400, detail="Гайд должен быть файлом .md")
    config = load_config()
    path = resolve_path(config["paths"]["style_guide"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (await file.read()).decode("utf-8", errors="replace")
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "exists": True, "content": content}


# --- индекс ----------------------------------------------------------------


@app.post("/api/reindex")
def reindex() -> dict[str, Any]:
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    if not docs_dir.exists():
        raise HTTPException(status_code=400, detail=f"Папка документации не найдена: {docs_dir}")
    if not indexer.find_markdown_files(docs_dir):
        raise HTTPException(status_code=400, detail=f"В папке {docs_dir} нет файлов .md")
    index = indexer.build_index(config, get_client(config))
    return indexer.index_summary(index)


@app.get("/api/documents")
def documents() -> dict[str, Any]:
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    files = indexer.find_markdown_files(docs_dir)
    return {
        "docs_dir": str(docs_dir),
        "documents": [
            {"path": path.relative_to(docs_dir).as_posix(), "title": indexer.document_title(indexer.read_text(path), path)}
            for path in files
        ],
    }


@app.get("/api/document")
def document(path: str) -> dict[str, Any]:
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    target = safe_join(docs_dir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {path}")
    return {"path": path, "content": indexer.read_text(target)}


# --- поиск -----------------------------------------------------------------


@app.post("/api/search")
def search_endpoint(payload: SearchRequest) -> dict[str, Any]:
    config = load_config()
    index = indexer.load_index(config)
    if not index or not index.get("sections"):
        raise HTTPException(status_code=400, detail="Индекс пуст. Нажмите «Переиндексировать».")
    top_k = payload.top_k or int(config["search"]["top_k"])
    candidates = search.search_documents(index, get_client(config), payload.query, top_k)
    return {"candidates": candidates}


# --- генерация -------------------------------------------------------------


@app.post("/api/generate")
def generate_endpoint(payload: GenerateRequest) -> dict[str, Any]:
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    source = safe_join(docs_dir, payload.doc_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {payload.doc_path}")

    original = indexer.read_text(source)
    style_guide = read_style_guide(config)
    result = generate_update(
        config=config,
        client=get_client(config),
        document=original,
        change_description=payload.change_description,
        style_guide=style_guide,
        doc_path=payload.doc_path,
    )
    updated = result["content"]
    if not updated.strip():
        raise HTTPException(status_code=502, detail="Модель вернула пустой ответ. Повторите запрос.")

    # Результат — всегда отдельный файл, оригинал не трогаем.
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_name = f"{slugify(Path(payload.doc_path).stem)}.{stamp}.md"
    out_path = output_dir / out_name
    out_path.write_text(updated, encoding="utf-8")

    return {
        "doc_path": payload.doc_path,
        "result_file": out_name,
        "result_path": str(out_path),
        "model": result["model"],
        "style_guide_used": bool(style_guide.strip()),
        "original": original,
        "updated": updated,
        "warnings": result["warnings"],
        "diff": build_diff(original, updated),
        "unified": unified_diff(original, updated, f"a/{payload.doc_path}", f"b/{out_name}"),
    }


@app.get("/api/download")
def download(file: str) -> FileResponse:
    config = load_config()
    output_dir = resolve_path(config["paths"]["output_dir"])
    target = safe_join(output_dir, file)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден.")
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@app.post("/api/apply")
def apply(payload: ApplyRequest) -> dict[str, Any]:
    """Явное подтверждение записи в оригинал. Перед перезаписью делается .bak."""
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    output_dir = resolve_path(config["paths"]["output_dir"])
    source = safe_join(docs_dir, payload.doc_path)
    result_file = safe_join(output_dir, payload.result_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Исходный документ не найден.")
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден.")

    backup = source.with_suffix(source.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(source, backup)
    source.write_text(result_file.read_text(encoding="utf-8"), encoding="utf-8")
    return {"applied": True, "doc_path": payload.doc_path, "backup": backup.name}


# --- фронтенд --------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
