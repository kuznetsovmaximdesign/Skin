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

from . import changeset as changeset_module
from . import article, checks, docmap, drift, impact, indexer, search, sections, style
from .checks import prose as prose_rules
from .verify import check_and_fix
from .config import (
    PROJECT_ROOT,
    default_product,
    for_product,
    load_config,
    product_ids,
    resolve_path,
    save_config,
    style_guide_paths,
)
from .diffing import build_diff, unified_diff
from .generator import check_result, generate_update, prepare_generation, review_document
from .ollama_client import OllamaClient, OllamaError, clean_model_output

app = FastAPI(title="Локальный сервис обновления документации", version="1.0.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# --- вспомогательное -------------------------------------------------------


def load_config_for(product: str | None = None) -> dict[str, Any]:
    """Настройки выбранного продукта. Продукты изолированы: свои документы, гайды, индекс."""
    config = load_config()
    try:
        return for_product(config, product)
    except KeyError:
        available = ", ".join(product_ids(config)) or "нет ни одного"
        raise HTTPException(
            status_code=404,
            detail=f"Продукт «{product}» не настроен. Доступные продукты: {available}.",
        )


def update_setting(product: str | None, section: str, values: dict[str, Any]) -> None:
    """Пишет настройку туда, где ей место: в общие правила или в переопределения продукта."""
    raw = load_config()
    if product and product != default_product(raw):
        entry = raw.setdefault("products", {}).setdefault("items", {}).setdefault(product, {})
        target = entry.setdefault(section, {})
    else:
        target = raw.setdefault(section, {})
    target.update(values)
    save_config(raw)


def get_client(config: dict[str, Any]) -> OllamaClient:
    return OllamaClient(
        host=config["ollama"]["host"],
        timeout=float(config["ollama"]["request_timeout"]),
        keep_alive=str(config["ollama"].get("keep_alive", "5m")),
    )


def free_memory_for(config: dict[str, Any], client: OllamaClient, wanted: str) -> None:
    """Выгружает «другую» модель, чтобы генерация и эмбеддинги не занимали память разом.

    На 18 ГБ единой памяти это разница между «работает» и «всё тормозит».
    """
    if not config["ollama"].get("sequential_models", True):
        return
    generation = config["ollama"]["generation_model"]
    embedding = config["ollama"]["embedding_model"]
    keep, drop = (generation, embedding) if wanted == "generation" else (embedding, generation)
    if drop and drop != keep:
        client.unload(drop)


def safe_join(base: Path, relative: str) -> Path:
    """Защита от выхода за пределы рабочей папки (../)."""
    candidate = (base / relative).resolve()
    base_resolved = base.resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise HTTPException(status_code=400, detail="Недопустимый путь к файлу.")
    return candidate


def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def derived_guide_path(config: dict[str, Any]) -> Path:
    return resolve_path(config["paths"].get("derived_guide", "data/derived-guide.md"))


def samples_dir(config: dict[str, Any]) -> Path:
    return resolve_path(config["paths"].get("samples_dir", "data/samples"))


def profile_path(config: dict[str, Any]) -> Path:
    return derived_guide_path(config).with_suffix(".json")


def read_style_guide(config: dict[str, Any]) -> str:
    """Все правила одним текстом: сначала обязательные файлы, затем формат из образцов.

    Явные правила идут первыми и объявлены главными — выведенный формат лишь дополняет их.
    """
    parts: list[str] = []
    for path in style_guide_paths(config):
        content = read_file(path).strip()
        if content:
            parts.append(f"## Обязательные правила оформления — файл {path.name}\n\n{content}")

    if config["paths"].get("use_derived_guide", True):
        derived = read_file(derived_guide_path(config)).strip()
        if derived:
            parts.append(
                "## Формат, изученный по образцам (следовать, если не противоречит правилам выше)"
                f"\n\n{derived}"
            )
    return "\n\n".join(parts)


def style_sources(config: dict[str, Any]) -> dict[str, Any]:
    """Из чего сейчас складываются правила — для интерфейса."""
    guides = [
        {"file": path.name, "path": str(path), "exists": path.exists(), "chars": len(read_file(path))}
        for path in style_guide_paths(config)
    ]
    derived = derived_guide_path(config)
    learned: dict[str, Any] = {"exists": derived.exists(), "path": str(derived)}
    if derived.exists():
        stored = read_file(profile_path(config))
        if stored:
            try:
                learned["profile"] = json.loads(stored)
            except json.JSONDecodeError:
                learned["profile"] = {}
        learned["learned_at"] = datetime.fromtimestamp(derived.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        learned["text"] = read_file(derived)
    return {
        "guides": guides,
        "derived": learned,
        "use_derived_guide": bool(config["paths"].get("use_derived_guide", True)),
        "samples_dir": str(samples_dir(config)),
    }


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


class ProposeRequest(BaseModel):
    doc_path: str
    change_description: str = Field(min_length=1)
    section_indexes: list[int] | None = None


class DecideRequest(BaseModel):
    edit_id: str
    accepted: bool
    comment: str = ""


class NewArticleRequest(BaseModel):
    title: str = Field(min_length=1)
    requirements: str = Field(min_length=1)
    file_name: str | None = None
    front_matter: dict[str, str] | None = None
    use_examples: bool = True


class ImpactRequest(BaseModel):
    change_description: str = Field(min_length=1)
    top_k: int = 8


class DriftRequest(BaseModel):
    change_description: str = ""
    doc_path: str = ""


class ReviewRequest(BaseModel):
    content: str = Field(min_length=1)


class SaveResultRequest(BaseModel):
    doc_path: str
    result_file: str
    content: str = Field(min_length=1)


class ApplyRequest(BaseModel):
    doc_path: str
    result_path: str


class StyleGuideText(BaseModel):
    content: str


class LearnFormatRequest(BaseModel):
    # Спросить ли модель сформулировать правила словами (медленнее, но подробнее).
    use_model: bool = True


class UseDerivedRequest(BaseModel):
    enabled: bool


# --- статус и конфигурация -------------------------------------------------


@app.get("/api/products")
def products() -> dict[str, Any]:
    """Список продуктов: у каждого свои документы, гайды, шаблон и индекс."""
    raw = load_config()
    items = (raw.get("products") or {}).get("items") or {}
    result = []
    for identifier in items:
        product_config = for_product(raw, identifier)
        result.append(
            {
                "id": identifier,
                "name": product_config.get("product_name", identifier),
                "docs_dir": str(resolve_path(product_config["paths"]["docs_dir"])),
                "index_file": str(resolve_path(product_config["paths"]["index_file"])),
                "documents": len(indexer.find_markdown_files(resolve_path(product_config["paths"]["docs_dir"]))),
                "indexed": indexer.index_exists(product_config),
                "style_guides": [path.name for path in style_guide_paths(product_config)],
            }
        )
    return {"default": default_product(raw), "products": result}


@app.get("/api/status")
def status(product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    guide_path = resolve_path(config["paths"]["style_guide"])
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
        "product": config.get("product", ""),
        "product_name": config.get("product_name", ""),
        "config": {
            "docs_dir": str(docs_dir),
            "docs_dir_raw": config["paths"]["docs_dir"],
            "docs_dir_exists": docs_dir.exists(),
            "style_guide": str(guide_path),
            "style_guide_raw": config["paths"]["style_guide"],
            "style_guide_exists": guide_path.exists(),
            "generation_model": config["ollama"]["generation_model"],
            "embedding_model": config["ollama"]["embedding_model"],
            "keep_alive": config["ollama"].get("keep_alive", "5m"),
            "sequential_models": bool(config["ollama"].get("sequential_models", True)),
            "top_k": config["search"]["top_k"],
        },
        "markdown_files": len(indexer.find_markdown_files(docs_dir)),
        "index": indexer.index_summary(config),
        "ollama": ollama,
    }


@app.post("/api/config")
def update_config(patch: ConfigPatch, product: str | None = None) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    ollama: dict[str, Any] = {}
    if patch.docs_dir:
        paths["docs_dir"] = patch.docs_dir.strip()
    if patch.style_guide:
        paths["style_guide"] = patch.style_guide.strip()
    if patch.generation_model:
        ollama["generation_model"] = patch.generation_model.strip()
    if patch.embedding_model:
        ollama["embedding_model"] = patch.embedding_model.strip()
    if paths:
        update_setting(product, "paths", paths)
    if ollama:
        update_setting(product, "ollama", ollama)
    return status(product)


# --- гайд по стилю ---------------------------------------------------------


@app.get("/api/style-guide")
def get_style_guide(product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    path = resolve_path(config["paths"]["style_guide"])
    return {"path": str(path), "exists": path.exists(), "content": read_style_guide(config)}


@app.put("/api/style-guide")
def put_style_guide(payload: StyleGuideText, product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    path = resolve_path(config["paths"]["style_guide"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.content, encoding="utf-8")
    return {"path": str(path), "exists": True, "content": payload.content}


@app.post("/api/style-guide/upload")
async def upload_style_guide(file: UploadFile = File(...), product: str | None = None) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith((".md", ".markdown", ".txt")):
        raise HTTPException(status_code=400, detail="Гайд должен быть файлом .md")
    config = load_config_for(product)
    path = resolve_path(config["paths"]["style_guide"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (await file.read()).decode("utf-8", errors="replace")
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "exists": True, "content": content}


# --- образцы оформления и обученный формат ---------------------------------


@app.get("/api/style-sources")
def style_sources_endpoint(product: str | None = None) -> dict[str, Any]:
    return style_sources(load_config_for(product))


@app.post("/api/style-guides/upload")
async def upload_style_guides(files: list[UploadFile] = File(...), product: str | None = None) -> dict[str, Any]:
    """Добавляет файлы с правилами оформления. Их может быть сколько угодно."""
    config = load_config_for(product)
    target_dir = resolve_path(config["paths"].get("rules_dir", "data/rules"))
    target_dir.mkdir(parents=True, exist_ok=True)

    added: list[str] = []
    for file in files:
        name = Path(file.filename or "rules.md").name
        if not name.lower().endswith((".md", ".markdown", ".txt")):
            raise HTTPException(status_code=400, detail=f"«{name}»: правила должны быть файлом .md")
        destination = target_dir / name
        destination.write_text((await file.read()).decode("utf-8", errors="replace"), encoding="utf-8")
        relative = str(destination.relative_to(PROJECT_ROOT)) if destination.is_relative_to(PROJECT_ROOT) else str(destination)
        guides = config["paths"].get("style_guides") or []
        if isinstance(guides, str):
            guides = [guides]
        if relative not in guides:
            guides.append(relative)
        config["paths"]["style_guides"] = guides
        added.append(name)

    update_setting(product, "paths", {"style_guides": config["paths"]["style_guides"]})
    return {"added": added, **style_sources(load_config_for(product))}


@app.delete("/api/style-guides")
def remove_style_guide(file: str, product: str | None = None) -> dict[str, Any]:
    """Убирает файл правил из списка (сам файл на диске остаётся)."""
    config = load_config_for(product)
    guides = config["paths"].get("style_guides") or []
    if isinstance(guides, str):
        guides = [guides]
    kept = [item for item in guides if Path(item).name != Path(file).name]
    values: dict[str, Any] = {"style_guides": kept}
    if config["paths"].get("style_guide") and Path(config["paths"]["style_guide"]).name == Path(file).name:
        values["style_guide"] = kept[0] if kept else ""
    update_setting(product, "paths", values)
    return style_sources(load_config_for(product))


@app.get("/api/samples")
def list_samples(product: str | None = None) -> dict[str, Any]:
    directory = samples_dir(load_config_for(product))
    files = sorted(directory.glob("*.md")) if directory.exists() else []
    return {
        "dir": str(directory),
        "samples": [{"file": path.name, "chars": path.stat().st_size} for path in files],
    }


@app.post("/api/samples/upload")
async def upload_samples(files: list[UploadFile] = File(...), product: str | None = None) -> dict[str, Any]:
    """Загрузка готовых документов-образцов, по которым сервис изучает формат."""
    directory = samples_dir(load_config_for(product))
    directory.mkdir(parents=True, exist_ok=True)
    added: list[str] = []
    for file in files:
        name = Path(file.filename or "sample.md").name
        if not name.lower().endswith((".md", ".markdown", ".txt")):
            raise HTTPException(status_code=400, detail=f"«{name}»: образец должен быть файлом .md")
        (directory / name).write_text(
            (await file.read()).decode("utf-8", errors="replace"), encoding="utf-8"
        )
        added.append(name)
    return {"added": added, **list_samples(product)}


@app.delete("/api/samples")
def remove_sample(file: str, product: str | None = None) -> dict[str, Any]:
    directory = samples_dir(load_config_for(product))
    target = safe_join(directory, Path(file).name)
    if target.exists():
        target.unlink()
    return list_samples()


@app.post("/api/format/learn")
def learn_format(payload: LearnFormatRequest, product: str | None = None) -> dict[str, Any]:
    """Разбирает образцы и запоминает формат: дальше он применяется сам при каждой генерации."""
    config = load_config_for(product)
    directory = samples_dir(config)
    files = sorted(directory.glob("*.md")) if directory.exists() else []
    if not files:
        raise HTTPException(
            status_code=400,
            detail=f"В папке образцов {directory} нет файлов .md. Загрузите примеры документов.",
        )

    profile = style.analyze_samples(files)
    measured = style.profile_to_markdown(profile)

    model_rules = ""
    if payload.use_model:
        client = get_client(config)
        free_memory_for(config, client, "generation")
        excerpts = [style.read_sample(path)[:3000] for path in files[:3]]
        model_rules = style.derive_rules_with_model(config, client, profile, excerpts)

    text = measured
    if model_rules.strip():
        text += "\n## Правила, сформулированные по образцам\n\n" + model_rules.strip() + "\n"

    target = derived_guide_path(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    profile_path(config).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    update_setting(product, "paths", {"use_derived_guide": True})

    return {
        "profile": profile,
        "text": text,
        "used_model": bool(model_rules.strip()),
        **style_sources(load_config_for(product)),
    }


@app.post("/api/format/use")
def toggle_derived(payload: UseDerivedRequest, product: str | None = None) -> dict[str, Any]:
    """Включает или выключает применение изученного формата."""
    update_setting(product, "paths", {"use_derived_guide": payload.enabled})
    return style_sources(load_config_for(product))


@app.delete("/api/format")
def forget_format(product: str | None = None) -> dict[str, Any]:
    """Забыть изученный формат."""
    config = load_config_for(product)
    for path in (derived_guide_path(config), profile_path(config)):
        if path.exists():
            path.unlink()
    return style_sources(load_config_for(product))


# --- индекс ----------------------------------------------------------------


@app.post("/api/reindex")
def reindex(product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    if not docs_dir.exists():
        raise HTTPException(status_code=400, detail=f"Папка документации не найдена: {docs_dir}")
    if not indexer.find_markdown_files(docs_dir):
        raise HTTPException(status_code=400, detail=f"В папке {docs_dir} нет файлов .md")
    client = get_client(config)
    free_memory_for(config, client, "embedding")
    return indexer.build_index(config, client)


@app.get("/api/map")
def document_map(product: str | None = None) -> dict[str, Any]:
    """Карта «документ ↔ что он документирует»."""
    config = load_config_for(product)
    documents = docmap.read_map(config)
    return {
        "documents": documents,
        "with_summary": sum(1 for item in documents if item["summary"]),
        "total": len(documents),
    }


@app.post("/api/map/build")
def build_document_map(force: bool = False, product: str | None = None) -> dict[str, Any]:
    """Считает недостающие резюме документов. Модели работают по очереди."""
    config = load_config_for(product)
    if not indexer.index_exists(config):
        raise HTTPException(status_code=400, detail="Индекс пуст. Сначала нажмите «Переиндексировать».")
    client = get_client(config)
    free_memory_for(config, client, "generation")
    return docmap.build_map(config, client, force=force)


@app.get("/api/documents")
def documents(product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
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
def document(path: str, product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    target = safe_join(docs_dir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {path}")
    return {"path": path, "content": indexer.read_text(target)}


@app.get("/api/outline")
def document_outline(path: str, product: str | None = None) -> dict[str, Any]:
    """Разделы документа — чтобы править один раздел, а не весь текст."""
    config = load_config_for(product)
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
def search_endpoint(payload: SearchRequest, product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    if not indexer.index_exists(config):
        raise HTTPException(status_code=400, detail="Индекс пуст. Нажмите «Переиндексировать».")
    top_k = payload.top_k or int(config["search"]["top_k"])
    client = get_client(config)
    free_memory_for(config, client, "embedding")
    candidates = search.search_documents(indexer.index_path(config), client, payload.query, top_k)
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


# --- changeset: правки принимаются поштучно --------------------------------


@app.post("/api/changeset/propose")
def propose_changeset(payload: ProposeRequest, product: str | None = None) -> dict[str, Any]:
    """Предлагает правки по разделам с обоснованием. Документ не меняется."""
    config = load_config_for(product)
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    source = safe_join(docs_dir, payload.doc_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {payload.doc_path}")

    client = get_client(config)
    free_memory_for(config, client, "generation")
    result = changeset_module.propose(
        config=config,
        client=client,
        doc_path=payload.doc_path,
        original=indexer.read_text(source),
        description=payload.change_description,
        style_guide=read_style_guide(config),
        section_indexes=payload.section_indexes,
        feedback=changeset_module.feedback_instruction(config, payload.doc_path),
    )
    return {**result, "summary": changeset_module.summarize(result)}


@app.get("/api/changeset/{changeset_id}")
def get_changeset(changeset_id: str, product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    result = changeset_module.load(config, changeset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Набор правок не найден.")
    return {**result, "summary": changeset_module.summarize(result)}


@app.post("/api/changeset/{changeset_id}/decide")
def decide_changeset(changeset_id: str, payload: DecideRequest, product: str | None = None) -> dict[str, Any]:
    """Писатель принимает или отклоняет отдельную правку; отклонения запоминаются."""
    config = load_config_for(product)
    result = changeset_module.load(config, changeset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Набор правок не найден.")
    if not any(edit["id"] == payload.edit_id for edit in result["edits"]):
        raise HTTPException(status_code=404, detail="Такой правки нет в наборе.")
    result = changeset_module.decide(config, result, payload.edit_id, payload.accepted, payload.comment)
    return {**result, "summary": changeset_module.summarize(result)}


@app.post("/api/changeset/{changeset_id}/build")
def build_changeset(changeset_id: str, product: str | None = None) -> dict[str, Any]:
    """Собирает документ из принятых правок и сохраняет отдельным файлом."""
    config = load_config_for(product)
    result = changeset_module.load(config, changeset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Набор правок не найден.")

    docs_dir = resolve_path(config["paths"]["docs_dir"])
    source = safe_join(docs_dir, result["doc_path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Исходный документ не найден.")

    original = indexer.read_text(source)
    accepted = [edit for edit in result["edits"] if edit["status"] == "accepted"]
    if not accepted:
        raise HTTPException(status_code=400, detail="Ни одна правка не принята — собирать нечего.")

    updated = changeset_module.build_document(original, result)
    request = GenerateRequest(doc_path=result["doc_path"], change_description=result["description"])
    out_path = store_result(
        config,
        request,
        updated,
        "changeset",
        ", ".join(edit["section"] for edit in accepted),
        result.get("model", ""),
        True,
    )
    return {
        "changeset_id": changeset_id,
        "doc_path": result["doc_path"],
        "result_file": out_path.name,
        "result_path": str(out_path),
        "applied_edits": len(accepted),
        "original": original,
        "updated": updated,
        "diff": build_diff(original, updated),
    }


@app.get("/api/feedback")
def feedback(doc_path: str = "", product: str | None = None) -> dict[str, Any]:
    """Локальный лог: что писатель отклонял раньше."""
    config = load_config_for(product)
    return {"notes": changeset_module.feedback_notes(config, doc_path)}


@app.post("/api/article/new")
def new_article(payload: NewArticleRequest, product: str | None = None) -> dict[str, Any]:
    """Черновик новой статьи по шаблону продукта. Проходит тот же цикл проверки, что и правки."""
    config = load_config_for(product)
    style_guide = read_style_guide(config)
    client = get_client(config)

    # Пример тона берём из ближайшей существующей статьи; факты из неё не используются.
    example = ""
    if payload.use_examples and indexer.index_exists(config):
        free_memory_for(config, client, "embedding")
        found = search.search_documents(
            indexer.index_path(config), client, payload.requirements, 1
        )
        if found:
            docs_dir = resolve_path(config["paths"]["docs_dir"])
            source = docs_dir / found[0]["path"]
            if source.exists():
                example = indexer.read_text(source)

    free_memory_for(config, client, "generation")
    drafted = article.draft(
        config=config,
        client=client,
        title=payload.title,
        requirements=payload.requirements,
        style_guide=style_guide,
        example=example,
        front_matter=payload.front_matter,
    )
    verified = check_and_fix(config, client, drafted["text"], style_guide, "document")

    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = slugify(payload.file_name or payload.title)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = unique_path(output_dir, f"{stem}.{stamp}", ".md")
    out_path.write_text(verified["text"], encoding="utf-8")
    write_meta(
        out_path,
        {
            "kind": "new-article",
            "title": payload.title,
            "product": config.get("product", ""),
            "change_description": payload.requirements[:500],
            "model": config["ollama"]["generation_model"],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "style_guide_used": bool(style_guide.strip()),
        },
    )

    return {
        "title": payload.title,
        "sections": drafted["sections"],
        "text": verified["text"],
        "result_file": out_path.name,
        "result_path": str(out_path),
        "example_from": found[0]["path"] if payload.use_examples and example else "",
        "checks": {
            "violations": verified["violations"],
            "summary": verified["summary"],
            "fix_iterations": verified["iterations"],
        },
    }


@app.post("/api/impact")
def impact_endpoint(payload: ImpactRequest, product: str | None = None) -> dict[str, Any]:
    """Все статьи, которых касается изменение: класс, релевантность и причина."""
    config = load_config_for(product)
    if not indexer.index_exists(config):
        raise HTTPException(status_code=400, detail="Индекс пуст. Нажмите «Переиндексировать».")
    client = get_client(config)
    free_memory_for(config, client, "embedding")
    return impact.analyze(config, client, payload.change_description, top_k=payload.top_k)


@app.post("/api/drift")
def drift_endpoint(payload: DriftRequest, product: str | None = None) -> dict[str, Any]:
    """«На что ещё посмотреть»: битые ссылки, устаревшие значения, следы удалённого, пометки."""
    config = load_config_for(product)
    docs_dir = resolve_path(config["paths"]["docs_dir"])
    if not docs_dir.exists():
        raise HTTPException(status_code=400, detail=f"Папка документации не найдена: {docs_dir}")

    settings = checks.checks_config(config)
    rules = prose_rules.load_rules(config, settings)
    glossary = {**(rules.get("glossary") or {}), **(rules.get("substitutions") or {})}
    return drift.scan(
        docs_dir,
        description=payload.change_description,
        only_doc=payload.doc_path,
        glossary=glossary,
    )


@app.post("/api/check")
def check_endpoint(payload: ReviewRequest, product: str | None = None) -> dict[str, Any]:
    """Проверка произвольного текста: формулировка, оформление, шаблон."""
    config = load_config_for(product)
    violations = checks.run_checks(payload.content, config)
    return {
        "violations": [item.as_dict() for item in violations],
        "summary": checks.summarize(violations),
    }


@app.post("/api/generate")
def generate_endpoint(payload: GenerateRequest, product: str | None = None) -> dict[str, Any]:
    config = load_config_for(product)
    context = load_generation_context(config, payload)
    original, style_guide = context["original"], context["style_guide"]
    span, section_payload = context["span"], context["section"]

    client = get_client(config)
    free_memory_for(config, client, "generation")
    result = generate_update(
        config=config,
        client=client,
        document=original,
        change_description=payload.change_description,
        style_guide=style_guide,
        doc_path=payload.doc_path,
        section=section_payload,
    )
    produced = result["content"]
    if not produced.strip():
        raise HTTPException(status_code=502, detail="Модель вернула пустой ответ. Повторите запрос.")

    # Единый цикл: сгенерировали → проверили → починили.
    verified = check_and_fix(
        config, client, produced, style_guide, "section" if span is not None else "document"
    )
    produced = verified["text"]
    updated = sections.replace_section(original, span, produced) if span is not None else produced

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
        "checks": {
            "violations": verified["violations"],
            "summary": verified["summary"],
            "fix_iterations": verified["iterations"],
        },
        "diff": build_diff(original, updated),
        "unified": unified_diff(original, updated, f"a/{payload.doc_path}", f"b/{out_name}"),
    }


@app.post("/api/generate/stream")
def generate_stream_endpoint(payload: GenerateRequest, product: str | None = None) -> StreamingResponse:
    """То же обновление, но текст отдаётся по мере генерации — писателю не нужно ждать вслепую."""
    config = load_config_for(product)
    context = load_generation_context(config, payload)
    original, style_guide = context["original"], context["style_guide"]
    span, section_payload = context["span"], context["section"]

    client = get_client(config)
    free_memory_for(config, client, "generation")
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
        if produced.strip():
            yield event("checking")
            verified = check_and_fix(
                config, client, produced, style_guide, "section" if span is not None else "document"
            )
            produced = verified["text"]
        else:
            verified = {"violations": [], "summary": {}, "iterations": 0}
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
            checks={
                "violations": verified["violations"],
                "summary": verified["summary"],
                "fix_iterations": verified["iterations"],
            },
            diff=build_diff(original, updated),
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/review")
def review_endpoint(payload: ReviewRequest, product: str | None = None) -> dict[str, Any]:
    """Проверка готового текста по гайду вторым проходом модели."""
    config = load_config_for(product)
    style_guide = read_style_guide(config)
    if not style_guide.strip():
        raise HTTPException(
            status_code=400,
            detail="Гайд по стилю пуст — проверять не по чему. Загрузите гайд в шаге 2.",
        )
    client = get_client(config)
    free_memory_for(config, client, "generation")
    result = review_document(config, client, payload.content, style_guide)
    return {"notes": result["notes"], "raw": result["raw"], "model": result["model"]}


@app.get("/api/download")
def download(file: str, product: str | None = None) -> FileResponse:
    config = load_config_for(product)
    output_dir = resolve_path(config["paths"]["output_dir"])
    target = safe_join(output_dir, file)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден.")
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@app.post("/api/results/save")
def save_result(payload: SaveResultRequest, product: str | None = None) -> dict[str, Any]:
    """Сохраняет правки, внесённые писателем вручную. Оригинал по-прежнему не трогаем."""
    config = load_config_for(product)
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
def results(limit: int = 20, product: str | None = None) -> dict[str, Any]:
    """Ранее сохранённые результаты — чтобы ничего не потерялось между сессиями."""
    config = load_config_for(product)
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
def apply(payload: ApplyRequest, product: str | None = None) -> dict[str, Any]:
    """Явное подтверждение записи в оригинал. Перед перезаписью делается .bak."""
    config = load_config_for(product)
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
    if indexer.index_exists(config):
        try:
            client = get_client(config)
            free_memory_for(config, client, "embedding")
            indexer.build_index(config, client)
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
