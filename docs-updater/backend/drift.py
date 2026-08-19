"""Детект расхождений в документации («docs drift») — офлайн-сигналы без модели.

Проверяем то, что видно детерминированно: битые внутренние ссылки и якоря, устаревшие
значения, упоминания удалённого или переименованного, оставшиеся пометки.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from . import indexer, sections

LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MARKER_RE = re.compile(r"\[уточнить[^\]]*\]|\bTODO\b|\bFIXME\b|\[спорно:[^\]]*\]", re.IGNORECASE)
VERSION_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
NUMBER_UNIT_RE = re.compile(r"\b(\d+)\s*(минут\w*|секунд\w*|часов|часа|час|дней|дня|день|раз\w*|МБ|ГБ|КБ)\b", re.IGNORECASE)
REMOVED_RE = re.compile(
    r"(?:убрал[иа]?|удалил[иа]?|отключил[иа]?|переименовал[иа]?|заменил[иа]?)\s+([«\"']?[\w./:-]+[»\"']?)",
    re.IGNORECASE,
)
CODE_TERM_RE = re.compile(r"`([^`\n]+)`")


@dataclass
class Finding:
    kind: str  # broken-link | stale-value | removed-mention | marker | glossary
    severity: str  # error | warning
    doc_path: str
    line: int
    message: str
    excerpt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def anchor(title: str) -> str:
    """Якорь заголовка в стиле GitHub: строчные буквы, пробелы — в дефисы."""
    slug = title.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    return re.sub(r"\s+", "-", slug).strip("-")


def iter_documents(docs_dir: Path) -> Iterator[tuple[str, str]]:
    for path in indexer.find_markdown_files(docs_dir):
        yield path.relative_to(docs_dir).as_posix(), indexer.read_text(path)


def check_links(docs_dir: Path, doc_path: str, text: str) -> list[Finding]:
    """Битые относительные ссылки и якоря."""
    findings: list[Finding] = []
    base = (docs_dir / doc_path).parent
    known_anchors = {anchor(span.title) for span in sections.outline(text)}

    for number, line in enumerate(text.split("\n"), start=1):
        for title, target in LINK_RE.findall(line):
            if target.startswith(("http://", "https://", "mailto:", "tel:")):
                continue  # внешние адреса не проверяем: сервис офлайн
            file_part, _, anchor_part = target.partition("#")

            if file_part:
                candidate = (base / file_part).resolve()
                if not candidate.exists():
                    findings.append(
                        Finding("broken-link", "error", doc_path, number,
                                f"Ссылка «{title}» ведёт в несуществующий файл {file_part}", target)
                    )
                    continue
                if anchor_part and candidate.suffix.lower() == ".md":
                    other = indexer.read_text(candidate)
                    if anchor(anchor_part) not in {anchor(span.title) for span in sections.outline(other)}:
                        findings.append(
                            Finding("broken-link", "error", doc_path, number,
                                    f"В файле {file_part} нет заголовка для якоря #{anchor_part}", target)
                        )
            elif anchor_part and anchor(anchor_part) not in known_anchors:
                findings.append(
                    Finding("broken-link", "error", doc_path, number,
                            f"В документе нет заголовка для якоря #{anchor_part}", target)
                )
    return findings


def check_markers(doc_path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.split("\n"), start=1):
        for match in MARKER_RE.finditer(line):
            findings.append(
                Finding("marker", "warning", doc_path, number,
                        "Осталась пометка, требующая внимания", match.group(0))
            )
    return findings


def new_values(description: str) -> dict[str, str]:
    """Новые значения из описания изменения: версии и числа с единицами."""
    values: dict[str, str] = {}
    for number, unit in NUMBER_UNIT_RE.findall(description or ""):
        values[f"{number} {unit.lower()}"] = unit.lower()
    for version in VERSION_RE.findall(description or ""):
        values[version] = "версия"
    return values


def check_stale_values(doc_path: str, text: str, description: str) -> list[Finding]:
    """Если изменение вводит новое значение, ищем в документах старые того же вида."""
    findings: list[Finding] = []
    wanted = new_values(description)
    if not wanted:
        return findings
    new_units = {unit for value, unit in wanted.items() if unit != "версия"}
    new_literals = set(wanted)

    for number, line in enumerate(text.split("\n"), start=1):
        for value, unit in NUMBER_UNIT_RE.findall(line):
            literal = f"{value} {unit.lower()}"
            if unit.lower() in new_units and literal not in new_literals:
                findings.append(
                    Finding("stale-value", "warning", doc_path, number,
                            f"Здесь указано «{literal}», а изменение вводит другое значение", literal)
                )
        if "версия" in wanted.values():
            for version in VERSION_RE.findall(line):
                if version not in new_literals:
                    findings.append(
                        Finding("stale-value", "warning", doc_path, number,
                                f"Здесь указана версия {version}, а изменение вводит другую", version)
                    )
    return findings


def removed_terms(description: str) -> list[str]:
    """Что, по описанию, убрали или переименовали."""
    terms: list[str] = []
    for match in REMOVED_RE.findall(description or ""):
        term = match.strip("«»\"'").strip()
        if len(term) > 2:
            terms.append(term)
    for term in CODE_TERM_RE.findall(description or ""):
        if re.search(r"(убрал|удалил|отключил|переименовал|заменил)", (description or "").lower()):
            terms.append(term.strip())
    return sorted(set(terms))


def check_removed_mentions(doc_path: str, text: str, terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.split("\n"), start=1):
        for term in terms:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", line, re.IGNORECASE):
                findings.append(
                    Finding("removed-mention", "warning", doc_path, number,
                            f"«{term}» ещё описан здесь, хотя изменение говорит, что его убрали", term)
                )
    return findings


def scan(
    docs_dir: Path,
    description: str = "",
    only_doc: str = "",
    glossary: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Собирает все сигналы расхождений по папке документации."""
    findings: list[Finding] = []
    terms = removed_terms(description)
    glossary = glossary or {}

    for doc_path, text in iter_documents(docs_dir):
        if only_doc and doc_path != only_doc:
            continue
        findings += check_links(docs_dir, doc_path, text)
        findings += check_markers(doc_path, text)
        if description:
            findings += check_stale_values(doc_path, text, description)
            if terms:
                findings += check_removed_mentions(doc_path, text, terms)
        for number, line in enumerate(text.split("\n"), start=1):
            for wrong, right in glossary.items():
                if re.search(rf"(?<!\w){re.escape(wrong)}(?!\w)", line, re.IGNORECASE):
                    findings.append(
                        Finding("glossary", "warning", doc_path, number,
                                f"Термин «{wrong}» вне глоссария, принято «{right}»", wrong)
                    )

    findings.sort(key=lambda item: (item.doc_path, item.line))
    return {
        "findings": [item.as_dict() for item in findings],
        "summary": {
            "total": len(findings),
            "errors": sum(1 for item in findings if item.severity == "error"),
            "by_kind": {
                kind: sum(1 for item in findings if item.kind == kind)
                for kind in sorted({item.kind for item in findings})
            },
            "removed_terms": terms,
        },
    }
