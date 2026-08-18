"""Diff «было / стало» по абзацам с пословной подсветкой внутри изменённых абзацев."""

from __future__ import annotations

import difflib
import re
from typing import Any

WORD_RE = re.compile(r"\s+|[^\s]+")


def split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n"))]
    return [part for part in parts if part]


def _tokens(text: str) -> list[str]:
    return WORD_RE.findall(text)


def inline_diff(old: str, new: str) -> dict[str, list[dict[str, str]]]:
    """Пословный diff двух абзацев: куски с пометкой same/removed/added."""
    old_tokens, new_tokens = _tokens(old), _tokens(new)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    old_parts: list[dict[str, str]] = []
    new_parts: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = "".join(old_tokens[i1:i2])
        new_chunk = "".join(new_tokens[j1:j2])
        if tag == "equal":
            old_parts.append({"type": "same", "text": old_chunk})
            new_parts.append({"type": "same", "text": new_chunk})
        else:
            if old_chunk:
                old_parts.append({"type": "removed", "text": old_chunk})
            if new_chunk:
                new_parts.append({"type": "added", "text": new_chunk})
    return {"old": old_parts, "new": new_parts}


def build_diff(old_text: str, new_text: str) -> dict[str, Any]:
    old_paragraphs = split_paragraphs(old_text)
    new_paragraphs = split_paragraphs(new_text)
    matcher = difflib.SequenceMatcher(a=old_paragraphs, b=new_paragraphs, autojunk=False)

    blocks: list[dict[str, Any]] = []
    stats = {"unchanged": 0, "added": 0, "removed": 0, "changed": 0}

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for index in range(i1, i2):
                blocks.append({"type": "equal", "old": old_paragraphs[index], "new": old_paragraphs[index]})
                stats["unchanged"] += 1
        elif tag == "delete":
            for index in range(i1, i2):
                blocks.append({"type": "delete", "old": old_paragraphs[index], "new": ""})
                stats["removed"] += 1
        elif tag == "insert":
            for index in range(j1, j2):
                blocks.append({"type": "insert", "old": "", "new": new_paragraphs[index]})
                stats["added"] += 1
        else:  # replace — сопоставляем абзацы попарно, остаток считаем удалением/вставкой
            old_chunk = old_paragraphs[i1:i2]
            new_chunk = new_paragraphs[j1:j2]
            pairs = min(len(old_chunk), len(new_chunk))
            for offset in range(pairs):
                old_paragraph, new_paragraph = old_chunk[offset], new_chunk[offset]
                blocks.append(
                    {
                        "type": "replace",
                        "old": old_paragraph,
                        "new": new_paragraph,
                        "inline": inline_diff(old_paragraph, new_paragraph),
                    }
                )
                stats["changed"] += 1
            for old_paragraph in old_chunk[pairs:]:
                blocks.append({"type": "delete", "old": old_paragraph, "new": ""})
                stats["removed"] += 1
            for new_paragraph in new_chunk[pairs:]:
                blocks.append({"type": "insert", "old": "", "new": new_paragraph})
                stats["added"] += 1

    return {"blocks": blocks, "stats": stats, "has_changes": stats["added"] + stats["removed"] + stats["changed"] > 0}


def unified_diff(old_text: str, new_text: str, old_name: str, new_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            (old_text or "").splitlines(keepends=True),
            (new_text or "").splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
        )
    )
