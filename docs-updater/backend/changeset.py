"""Changeset: правки предлагаются по одной, с обоснованием, и принимаются писателем поштучно.

Каждая правка ссылается на конкретное предложение из описания изменения. Если модель
хочет тронуть то, что описанием не обосновано, правка помечается как предположение.
Ничего не применяется автоматически — итоговый документ собирается только из принятых правок.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import generator, sections
from .config import resolve_path
from .ollama_client import OllamaClient
from .verify import check_and_fix

REASON_RE = re.compile(r"^\s*ОБОСНОВАНИЕ:\s*(.+)$", re.MULTILINE)
ASSUMPTION_RE = re.compile(r"^\s*ПРЕДПОЛОЖЕНИЕ:\s*(.+)$", re.MULTILINE)

PROVENANCE_INSTRUCTION = """

Обязательно закончи ответ двумя служебными строками:
ОБОСНОВАНИЕ: <дословная цитата из описания изменения, которая требует этой правки>
ПРЕДПОЛОЖЕНИЕ: <«да», если правка не следует напрямую из описания, иначе «нет»>"""


def changesets_dir(config: dict[str, Any]) -> Path:
    return resolve_path(config["paths"].get("changesets_dir", "data/changesets"))


def feedback_path(config: dict[str, Any]) -> Path:
    return resolve_path(config["paths"].get("feedback_log", "data/feedback.jsonl"))


# --- определение затронутых разделов ---------------------------------------


def split_statements(description: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", description or "")
    return [part.strip() for part in parts if part.strip()]


def affected_sections(
    original: str,
    description: str,
    client: OllamaClient,
    embedding_model: str,
    limit: int = 4,
    threshold: float = 0.25,
) -> list[tuple[int, float]]:
    """Какие разделы реально затронуты изменением: сравниваем их с описанием локально."""
    from .search import cosine

    spans = sections.outline(original)
    if not spans:
        return []
    texts = [sections.section_text(original, span) for span in spans]
    vectors = client.embed(embedding_model, [description, *texts])
    query, section_vectors = vectors[0], vectors[1:]

    scored = [
        (span.index, cosine(query, vector))
        for span, vector in zip(spans, section_vectors)
        if span.level > 1 or len(spans) == 1
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    chosen = [item for item in scored if item[1] >= threshold][:limit]
    return chosen or scored[:1]


# --- предложение правок -----------------------------------------------------


def parse_provenance(answer: str, description: str) -> dict[str, Any]:
    """Достаёт обоснование и признак предположения, возвращает текст без служебных строк."""
    reason_match = REASON_RE.search(answer)
    assumption_match = ASSUMPTION_RE.search(answer)
    reason = reason_match.group(1).strip() if reason_match else ""
    assumption = bool(assumption_match and assumption_match.group(1).strip().lower().startswith("да"))

    text = REASON_RE.sub("", answer)
    text = ASSUMPTION_RE.sub("", text).strip()

    normalized = re.sub(r"\s+", " ", (description or "").lower())
    quote = re.sub(r"\s+", " ", reason.lower()).strip(" «»\"'.")
    grounded = bool(quote) and quote in normalized
    if not grounded and reason:
        # Цитата не дословная — считаем правку предположением, а не обоснованной.
        assumption = True
    return {"reason": reason, "assumption": assumption or not reason, "grounded": grounded, "text": text}


def confidence_of(score: float, provenance: dict[str, Any], violations: int) -> str:
    if provenance["grounded"] and score >= 0.4 and violations == 0:
        return "высокая"
    if provenance["assumption"] or score < 0.25:
        return "низкая"
    return "средняя"


def propose(
    config: dict[str, Any],
    client: OllamaClient,
    doc_path: str,
    original: str,
    description: str,
    style_guide: str,
    section_indexes: list[int] | None = None,
    feedback: str = "",
) -> dict[str, Any]:
    """Готовит набор предложенных правок по разделам. Документ при этом не меняется."""
    spans = sections.outline(original)
    if section_indexes:
        targets = [(index, 1.0) for index in section_indexes if 0 <= index < len(spans)]
    else:
        targets = affected_sections(
            original, description, client, config["ollama"]["embedding_model"]
        )

    guide = style_guide
    if feedback:
        guide = (
            f"{guide}\n\n## Прошлые правила-исправления от писателя (не повторять отклонённое)"
            f"\n\n{feedback}"
        )

    edits: list[dict[str, Any]] = []
    for index, score in targets:
        span = spans[index]
        section_text = sections.section_text(original, span)
        payload = {
            "title": span.title,
            "path": span.path,
            "text": section_text,
            "outline": sections.document_map(original),
        }
        result = generator.generate_update(
            config=config,
            client=client,
            document=original,
            change_description=description + PROVENANCE_INSTRUCTION,
            style_guide=guide,
            doc_path=doc_path,
            section=payload,
        )
        provenance = parse_provenance(result["content"], description)
        if not provenance["text"].strip():
            continue

        verified = check_and_fix(config, client, provenance["text"], guide, "section")
        new_text = verified["text"]
        if new_text.strip() == section_text.strip():
            continue  # правка ничего не меняет — не показываем её писателю

        edits.append(
            {
                "id": uuid.uuid4().hex[:8],
                "section_index": index,
                "section": span.path,
                "old": section_text,
                "new": new_text,
                "reason": provenance["reason"],
                "assumption": provenance["assumption"],
                "grounded": provenance["grounded"],
                "relevance": round(score, 3),
                "confidence": confidence_of(score, provenance, verified["summary"].get("errors", 0)),
                "checks": verified["summary"],
                "violations": verified["violations"],
                "status": "pending",
                "comment": "",
            }
        )

    changeset = {
        "id": uuid.uuid4().hex[:10],
        "doc_path": doc_path,
        "description": description,
        "statements": split_statements(description),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": config["ollama"]["generation_model"],
        "edits": edits,
    }
    save(config, changeset)
    return changeset


# --- хранение и решения писателя --------------------------------------------


def path_for(config: dict[str, Any], changeset_id: str) -> Path:
    return changesets_dir(config) / f"{changeset_id}.json"


def save(config: dict[str, Any], changeset: dict[str, Any]) -> None:
    directory = changesets_dir(config)
    directory.mkdir(parents=True, exist_ok=True)
    path_for(config, changeset["id"]).write_text(
        json.dumps(changeset, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load(config: dict[str, Any], changeset_id: str) -> dict[str, Any] | None:
    path = path_for(config, changeset_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def decide(
    config: dict[str, Any],
    changeset: dict[str, Any],
    edit_id: str,
    accepted: bool,
    comment: str = "",
) -> dict[str, Any]:
    for edit in changeset["edits"]:
        if edit["id"] == edit_id:
            edit["status"] = "accepted" if accepted else "rejected"
            edit["comment"] = comment
            if not accepted:
                log_feedback(config, changeset, edit, comment)
            break
    save(config, changeset)
    return changeset


def build_document(original: str, changeset: dict[str, Any]) -> str:
    """Собирает документ из принятых правок; остальные разделы остаются байт-в-байт."""
    accepted = [edit for edit in changeset["edits"] if edit["status"] == "accepted"]
    text = original
    # Идём с конца, чтобы границы разделов выше по документу не сдвигались.
    for edit in sorted(accepted, key=lambda item: item["section_index"], reverse=True):
        spans = sections.outline(text)
        if 0 <= edit["section_index"] < len(spans):
            text = sections.replace_section(text, spans[edit["section_index"]], edit["new"])
    return text


# --- локальный лог обратной связи -------------------------------------------


def log_feedback(
    config: dict[str, Any], changeset: dict[str, Any], edit: dict[str, Any], comment: str
) -> None:
    """Отклонения писателя сохраняются локально и попадают в будущие инструкции модели."""
    path = feedback_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "doc_path": changeset["doc_path"],
        "section": edit["section"],
        "reason": edit.get("reason", ""),
        "comment": comment,
        "rejected_excerpt": edit["new"][:400],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def feedback_notes(config: dict[str, Any], doc_path: str = "", limit: int = 10) -> list[dict[str, Any]]:
    path = feedback_path(config)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not doc_path or record.get("doc_path") == doc_path:
            records.append(record)
    return records[-limit:]


def feedback_instruction(config: dict[str, Any], doc_path: str = "") -> str:
    notes = feedback_notes(config, doc_path)
    if not notes:
        return ""
    lines = []
    for note in notes:
        comment = note.get("comment") or "правка отклонена без комментария"
        lines.append(f"- В разделе «{note.get('section', '')}» писатель отклонил правку: {comment}")
    return "\n".join(lines)


def summarize(changeset: dict[str, Any]) -> dict[str, Any]:
    statuses = [edit["status"] for edit in changeset["edits"]]
    return {
        "total": len(statuses),
        "pending": statuses.count("pending"),
        "accepted": statuses.count("accepted"),
        "rejected": statuses.count("rejected"),
        "assumptions": sum(1 for edit in changeset["edits"] if edit["assumption"]),
    }
