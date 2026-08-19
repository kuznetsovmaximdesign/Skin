"""FastAPI-приложение локального сервиса обновления документации.

Никаких внешних сетевых обращений: только localhost:11434 (Ollama).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import indexer, search, sections
from .config import load_config, resolve_path, save_config
from .diffing import build_diff, unified_diff
from .generator import check_result, generate_update, prepare_generation
from .ollama_client import OllamaClient, OllamaError, clean_model_output

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


def meta_path(result_path: Path) -> Path:
    return result_path.with_suffix(result_path.suffix + ".json")


def write_meta(result_path: Path, meta: dict[str, Any]) -> None:
    """Рядом с результатом храним, из какого документа и по какому описанию он сделан."""
    meta_path(result_path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_meta(result_path: Path) -> dict[str, Any]:
    path = meta_path(result_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Не перезаписываем ранее сохранённый результат, даже если он создан в ту же секунду."""
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


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
    # Номер раздела из /api/outline. None — правим документ целиком.
    section_index: int | None = None


class SaveResultRequest(BaseModel):
    doc_path: str
    result_file: str
    content: str = Field(min_length=1)


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


@app.get("/api/outline")
def document_outline(path: str) -> dict[str, Any]:
    """Разделы документа — чтобы править один раздел, а не весь текст."""
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    target = safe_join(docs_dir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {path}")
    content = indexer.read_text(target)
    return {
        "path": path,
        "sections": [
            {
                "index": span.index,
                "level": span.level,
                "title": span.title,
                "path": span.path,
                "chars": len(sections.section_text(content, span)),
            }
            for span in sections.outline(content)
        ],
    }


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


def load_generation_context(config: dict[str, Any], payload: GenerateRequest) -> dict[str, Any]:
    """Читает документ, гайд и выбранный раздел — общая часть обычной и потоковой генерации."""
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    source = safe_join(docs_dir, payload.doc_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {payload.doc_path}")

    original = indexer.read_text(source)
    style_guide = read_style_guide(config)

    section_payload = None
    span = None
    if payload.section_index is not None:
        spans = sections.outline(original)
        if not 0 <= payload.section_index < len(spans):
            raise HTTPException(status_code=400, detail="Такого раздела нет в документе.")
        span = spans[payload.section_index]
        section_payload = {
            "title": span.title,
            "path": span.path,
            "text": sections.section_text(original, span),
            "outline": sections.document_map(original),
        }
    return {
        "original": original,
        "style_guide": style_guide,
        "section": section_payload,
        "span": span,
    }


def store_result(
    config: dict[str, Any],
    payload: GenerateRequest,
    updated: str,
    mode: str,
    section_path: str,
    model: str,
    style_guide_used: bool,
) -> Path:
    """Сохраняет результат отдельным файлом вместе с описанием правки."""
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = slugify(Path(payload.doc_path).stem)
    out_path = unique_path(output_dir, f"{stem}.{stamp}", ".md")
    out_path.write_text(updated, encoding="utf-8")
    write_meta(
        out_path,
        {
            "doc_path": payload.doc_path,
            "change_description": payload.change_description,
            "mode": mode,
            "section": section_path,
            "model": model,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "style_guide_used": style_guide_used,
        },
    )
    return out_path


@app.post("/api/generate")
def generate_endpoint(payload: GenerateRequest) -> dict[str, Any]:
    config = load_config()
    context = load_generation_context(config, payload)
    original, style_guide = context["original"], context["style_guide"]
    span, section_payload = context["span"], context["section"]

    result = generate_update(
        config=config,
        client=get_client(config),
        document=original,
        change_description=payload.change_description,
        style_guide=style_guide,
        doc_path=payload.doc_path,
        section=section_payload,
    )
    updated = result["content"]
    if not updated.strip():
        raise HTTPException(status_code=502, detail="Модель вернула пустой ответ. Повторите запрос.")
    if span is not None:
        updated = sections.replace_section(original, span, updated)

    # Результат — всегда отдельный файл, оригинал не трогаем.
    out_path = store_result(
        config,
        payload,
        updated,
        result["mode"],
        span.path if span else "",
        result["model"],
        bool(style_guide.strip()),
    )
    out_name = out_path.name

    return {
        "doc_path": payload.doc_path,
        "result_file": out_name,
        "result_path": str(out_path),
        "model": result["model"],
        "mode": result["mode"],
        "section": span.path if span else "",
        "style_guide_used": bool(style_guide.strip()),
        "original": original,
        "updated": updated,
        "warnings": result["warnings"],
        "diff": build_diff(original, updated),
        "unified": unified_diff(original, updated, f"a/{payload.doc_path}", f"b/{out_name}"),
    }


@app.post("/api/generate/stream")
def generate_stream_endpoint(payload: GenerateRequest) -> StreamingResponse:
    """То же обновление, но текст отдаётся по мере генерации — писателю не нужно ждать вслепую."""
    config = load_config()
    context = load_generation_context(config, payload)
    original, style_guide = context["original"], context["style_guide"]
    span, section_payload = context["span"], context["section"]

    client = get_client(config)
    plan = prepare_generation(
        config, original, payload.change_description, style_guide, payload.doc_path, section_payload
    )
    client.ensure_model(plan["model"])  # проверяем модель до начала потока, чтобы вернуть понятную ошибку

    def event(name: str, **fields: Any) -> str:
        return json.dumps({"type": name, **fields}, ensure_ascii=False) + "\n"

    def stream() -> Iterator[str]:
        yield event(
            "start",
            mode=plan["mode"],
            section=span.path if span else "",
            model=plan["model"],
            warnings=plan["warnings"],
        )
        pieces: list[str] = []
        try:
            for piece in client.generate_stream(
                model=plan["model"],
                prompt=plan["prompt"],
                system=plan["system"],
                temperature=plan["temperature"],
                num_ctx=plan["num_ctx"],
            ):
                pieces.append(piece)
                yield event("chunk", text=piece)
        except OllamaError as exc:
            yield event("error", **exc.as_dict())
            return

        produced = clean_model_output("".join(pieces))
        if not produced.strip():
            yield event(
                "error",
                error="Модель вернула пустой ответ.",
                hint="Переформулируйте описание изменения и повторите.",
            )
            return

        updated = sections.replace_section(original, span, produced) if span is not None else produced
        out_path = store_result(
            config,
            payload,
            updated,
            plan["mode"],
            span.path if span else "",
            plan["model"],
            bool(style_guide.strip()),
        )
        yield event(
            "done",
            doc_path=payload.doc_path,
            result_file=out_path.name,
            result_path=str(out_path),
            model=plan["model"],
            mode=plan["mode"],
            section=span.path if span else "",
            style_guide_used=bool(style_guide.strip()),
            original=original,
            updated=updated,
            warnings=plan["warnings"] + check_result(plan["original"], produced),
            diff=build_diff(original, updated),
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/download")
def download(file: str) -> FileResponse:
    config = load_config()
    output_dir = resolve_path(config["paths"]["output_dir"])
    target = safe_join(output_dir, file)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден.")
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@app.post("/api/results/save")
def save_result(payload: SaveResultRequest) -> dict[str, Any]:
    """Сохраняет правки, внесённые писателем вручную. Оригинал по-прежнему не трогаем."""
    config = load_config()
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    output_dir = resolve_path(config["paths"]["output_dir"])
    source = safe_join(docs_dir, payload.doc_path)
    target = safe_join(output_dir, payload.result_file)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Исходный документ не найден.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден.")

    target.write_text(payload.content, encoding="utf-8")
    meta = read_meta(target)
    meta["edited_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta.setdefault("doc_path", payload.doc_path)
    write_meta(target, meta)
    original = indexer.read_text(source)
    return {
        "result_file": target.name,
        "result_path": str(target),
        "updated": payload.content,
        "diff": build_diff(original, payload.content),
        "warnings": check_result(original, payload.content),
    }


@app.get("/api/results")
def results(limit: int = 20) -> dict[str, Any]:
    """Ранее сохранённые результаты — чтобы ничего не потерялось между сессиями."""
    config = load_config()
    output_dir = resolve_path(config["paths"]["output_dir"])
    if not output_dir.exists():
        return {"output_dir": str(output_dir), "results": []}
    files = sorted(output_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return {
        "output_dir": str(output_dir),
        "results": [
            {
                "file": path.name,
                "size": path.stat().st_size,
                "saved_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                **{
                    key: value
                    for key, value in read_meta(path).items()
                    if key in {"doc_path", "change_description", "mode", "section", "model", "edited_at"}
                },
            }
            for path in files[:limit]
        ],
    }


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

    # Индекс устарел: пересобираем его (пересчитаются только изменившиеся секции).
    index_updated = False
    if indexer.load_index(config):
        try:
            indexer.build_index(config, get_client(config))
            index_updated = True
        except OllamaError:
            index_updated = False

    return {
        "applied": True,
        "doc_path": payload.doc_path,
        "backup": backup.name,
        "index_updated": index_updated,
    }


# --- фронтенд --------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
