"""Слой 0: приём входящего и запись в inbox_raw до любого разбора.

Разбора на этом этапе нет. Задача одна: ничего не потерять.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import Database, utc_now_iso

log = logging.getLogger(__name__)

REACTION_RECEIVED = "👀"
DEDUP_WINDOW = timedelta(minutes=1)


@dataclass(frozen=True)
class IntakePlan:
    """Что именно пришло: вид, текст, файл, нужна ли расшифровка."""

    kind: str
    text: str | None = None
    file_id: str | None = None
    file_suffix: str = ""
    needs_transcript: bool = False
    unsupported: bool = False


def is_forwarded(message: Any) -> bool:
    return any(
        getattr(message, attr, None) is not None
        for attr in ("forward_origin", "forward_from", "forward_from_chat", "forward_sender_name", "forward_date")
    )


def _suffix_from_name(name: str | None, default: str) -> str:
    if name and "." in name:
        return "." + name.rsplit(".", 1)[-1].lower()[:8]
    return default


def plan_intake(message: Any) -> IntakePlan:
    """Определяет вид сообщения. Чистая функция, сети не касается.

    Виды берутся из схемы: text | voice | photo | forward. Пересланное — всегда
    forward, даже если внутри голос или фото: так записано в схеме.
    """
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    forwarded = is_forwarded(message)

    file_id: str | None = None
    suffix = ""
    needs_transcript = False
    unsupported = False
    kind = "text"

    voice = getattr(message, "voice", None)
    audio = getattr(message, "audio", None)
    video_note = getattr(message, "video_note", None)
    photo = getattr(message, "photo", None)
    document = getattr(message, "document", None)

    if voice is not None:
        kind, file_id, suffix, needs_transcript = "voice", voice.file_id, ".ogg", True
    elif audio is not None:
        kind, file_id, needs_transcript = "voice", audio.file_id, True
        suffix = _suffix_from_name(getattr(audio, "file_name", None), ".mp3")
    elif video_note is not None:
        kind, file_id, suffix, needs_transcript = "voice", video_note.file_id, ".mp4", True
    elif photo:
        kind, file_id, suffix = "photo", photo[-1].file_id, ".jpg"
    elif document is not None:
        mime = (getattr(document, "mime_type", None) or "").lower()
        file_id = document.file_id
        suffix = _suffix_from_name(getattr(document, "file_name", None), "")
        if mime.startswith("image/"):
            kind = "photo"
            suffix = suffix or ".jpg"
        elif mime.startswith("audio/") or mime.startswith("video/"):
            kind, needs_transcript = "voice", True
            suffix = suffix or ".ogg"
        else:
            # Вида для произвольного файла в схеме нет. Сохраняем как text
            # с путём к файлу: сообщение не теряется, схема не меняется.
            kind, unsupported = "text", True
    elif text is None:
        # Стикер, опрос, локация и прочее без текста и без файла.
        unsupported = True

    if forwarded:
        kind = "forward"

    return IntakePlan(
        kind=kind,
        text=text,
        file_id=file_id,
        file_suffix=suffix,
        needs_transcript=needs_transcript,
        unsupported=unsupported,
    )


def is_duplicate(db: Database, tg_message_id: int | None, now: datetime | None = None) -> bool:
    """Тот же tg_message_id за последнюю минуту — повтор, второй раз не пишем."""
    if tg_message_id is None:
        return False
    row = db.find_raw_by_tg_id(tg_message_id)
    if row is None:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(str(row["created_at"]))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return now - created <= DEDUP_WINDOW


def build_file_path(files_dir: Path, raw_id: int, plan: IntakePlan, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    return files_dir / day / f"{raw_id}{plan.file_suffix}"


class Intake:
    """Приём сообщения: запись, файл, расшифровка, реакция — именно в этом порядке."""

    def __init__(self, db: Database, files_dir: Path, transcriber: Any | None = None) -> None:
        self.db = db
        self.files_dir = Path(files_dir)
        self.transcriber = transcriber

    async def accept(self, message: Any, bot: Any) -> int | None:
        plan = plan_intake(message)
        tg_message_id = getattr(message, "message_id", None)

        if await asyncio.to_thread(is_duplicate, self.db, tg_message_id):
            log.info("повтор сообщения %s, пропускаю", tg_message_id)
            return None

        raw_id = await asyncio.to_thread(
            self.db.save_raw,
            kind=plan.kind,
            tg_message_id=tg_message_id,
            text=plan.text,
            created_at=utc_now_iso(),
        )
        log.info("inbox_raw %s: kind=%s, text=%s", raw_id, plan.kind, bool(plan.text))
        if plan.unsupported:
            log.warning("вид сообщения %s не описан в схеме, сохранён как text", raw_id)

        file_path: Path | None = None
        if plan.file_id:
            file_path = await self._download(bot, plan, raw_id)

        if plan.needs_transcript and file_path is not None:
            await self._transcribe(raw_id, file_path)

        await self._react(bot, message)
        return raw_id

    async def _download(self, bot: Any, plan: IntakePlan, raw_id: int) -> Path | None:
        path = build_file_path(self.files_dir, raw_id, plan)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            await bot.download(plan.file_id, destination=path)
        except Exception as exc:  # файл не скачался — строка уже в базе, текст цел
            log.exception("не скачал файл для inbox_raw %s", raw_id)
            await asyncio.to_thread(self.db.set_error, raw_id, f"download: {exc}")
            return None
        await asyncio.to_thread(self.db.set_file_path, raw_id, str(path))
        return path

    async def _transcribe(self, raw_id: int, path: Path) -> None:
        if self.transcriber is None or not self.transcriber.available:
            log.info("расшифровка выключена, inbox_raw %s остался без транскрипта", raw_id)
            return
        try:
            text = await asyncio.to_thread(self.transcriber.transcribe, path)
        except Exception as exc:
            log.exception("не расшифровал inbox_raw %s", raw_id)
            await asyncio.to_thread(self.db.set_error, raw_id, f"whisper: {exc}")
            return
        if text:
            await asyncio.to_thread(self.db.set_transcript, raw_id, text)
            log.info("inbox_raw %s расшифрован, %s символов", raw_id, len(text))

    async def _react(self, bot: Any, message: Any) -> None:
        """Реакция — единственный ответ на этом этапе. Её отказ ничего не ломает."""
        try:
            from aiogram.types import ReactionTypeEmoji

            await bot.set_message_reaction(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reaction=[ReactionTypeEmoji(emoji=REACTION_RECEIVED)],
            )
        except Exception:
            log.warning("реакция не поставлена на сообщение %s", getattr(message, "message_id", None))
