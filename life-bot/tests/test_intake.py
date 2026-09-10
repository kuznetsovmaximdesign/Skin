"""Определение вида сообщения и приём: сохранение, файл, расшифровка, реакция."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


from life_bot.db import Database
from life_bot.intake import Intake, build_file_path, is_duplicate, plan_intake


def msg(**kwargs):
    base = dict(
        message_id=1, text=None, caption=None, voice=None, audio=None, video_note=None,
        photo=None, document=None, forward_origin=None, forward_from=None,
        forward_from_chat=None, forward_sender_name=None, forward_date=None,
        chat=SimpleNamespace(id=100),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def file(file_id="f1", **kwargs):
    return SimpleNamespace(file_id=file_id, **kwargs)


def test_text():
    plan = plan_intake(msg(text="напомни про ОСАГО"))
    assert (plan.kind, plan.text, plan.file_id) == ("text", "напомни про ОСАГО", None)
    assert not plan.needs_transcript


def test_voice():
    plan = plan_intake(msg(voice=file("v1")))
    assert plan.kind == "voice"
    assert plan.file_id == "v1"
    assert plan.file_suffix == ".ogg"
    assert plan.needs_transcript


def test_photo_takes_largest_size():
    plan = plan_intake(msg(photo=[file("small"), file("big")], caption="борщ"))
    assert plan.kind == "photo"
    assert plan.file_id == "big"
    assert plan.text == "борщ"


def test_forward_wins_over_inner_type():
    plan = plan_intake(msg(voice=file("v1"), forward_origin=object()))
    assert plan.kind == "forward"
    assert plan.needs_transcript  # расшифровать всё равно надо


def test_audio_and_video_note_go_to_voice():
    assert plan_intake(msg(audio=file("a", file_name="запись.m4a"))).file_suffix == ".m4a"
    assert plan_intake(msg(video_note=file("vn"))).kind == "voice"


def test_image_document_is_photo():
    plan = plan_intake(msg(document=file("d", mime_type="image/png", file_name="скан.png")))
    assert plan.kind == "photo"
    assert plan.file_suffix == ".png"
    assert not plan.unsupported


def test_pdf_document_saved_as_text_with_file():
    plan = plan_intake(msg(document=file("d", mime_type="application/pdf", file_name="анализ.pdf")))
    assert plan.kind == "text"       # вида для файла в схеме нет
    assert plan.file_id == "d"       # но файл всё равно скачиваем
    assert plan.unsupported


def test_sticker_without_text_is_flagged():
    plan = plan_intake(msg())
    assert plan.kind == "text"
    assert plan.unsupported


def test_duplicate_within_a_minute(db: Database):
    db.save_raw(kind="text", tg_message_id=7, text="раз")
    assert is_duplicate(db, 7)
    assert not is_duplicate(db, 8)


def test_same_id_after_a_minute_is_not_duplicate(db: Database):
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    db.save_raw(kind="text", tg_message_id=7, text="раз", created_at=old)
    assert not is_duplicate(db, 7)


def test_file_path_is_grouped_by_day():
    now = datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc)
    plan = plan_intake(msg(voice=file("v1")))
    path = build_file_path(Path("/var/files"), 42, plan, now=now)
    assert path == Path("/var/files/2026-09-08/42.ogg")


class FakeBot:
    def __init__(self, fail_download=False):
        self.fail_download = fail_download
        self.reactions = []
        self.downloaded = []

    async def download(self, file_id, destination):
        if self.fail_download:
            raise RuntimeError("сеть отвалилась")
        self.downloaded.append(file_id)
        Path(destination).write_bytes(b"data")

    async def set_message_reaction(self, chat_id, message_id, reaction):
        self.reactions.append((chat_id, message_id, reaction[0].emoji))


class FakeTranscriber:
    def __init__(self, text="купить молоко", available=True, boom=False):
        self.text = text
        self.available = available
        self.boom = boom

    def transcribe(self, path):
        if self.boom:
            raise RuntimeError("модель не загрузилась")
        return self.text


async def test_text_message_is_saved(db: Database, tmp_path):
    bot = FakeBot()
    intake = Intake(db, tmp_path / "files")
    raw_id = await intake.accept(msg(message_id=5, text="привет"), bot)

    row = db.get_raw(raw_id)
    assert (row["kind"], row["text"], row["parse_state"]) == ("text", "привет", "new")
    assert bot.reactions == []          # реакции убраны, обратная связь текстом


async def test_voice_saved_downloaded_transcribed(db: Database, tmp_path):
    bot = FakeBot()
    intake = Intake(db, tmp_path / "files", FakeTranscriber())
    raw_id = await intake.accept(msg(message_id=6, voice=file("v1")), bot)

    row = db.get_raw(raw_id)
    assert row["kind"] == "voice"
    assert row["transcript"] == "купить молоко"
    assert Path(row["file_path"]).exists()
    assert bot.downloaded == ["v1"]


async def test_photo_saved_without_transcript(db: Database, tmp_path):
    bot = FakeBot()
    intake = Intake(db, tmp_path / "files", FakeTranscriber())
    raw_id = await intake.accept(msg(message_id=7, photo=[file("p1")], caption="борщ"), bot)

    row = db.get_raw(raw_id)
    assert (row["kind"], row["text"], row["transcript"]) == ("photo", "борщ", None)
    assert Path(row["file_path"]).exists()


async def test_download_failure_keeps_the_message(db: Database, tmp_path):
    bot = FakeBot(fail_download=True)
    intake = Intake(db, tmp_path / "files", FakeTranscriber())
    raw_id = await intake.accept(msg(message_id=8, voice=file("v1"), caption="про подрядчика"), bot)

    row = db.get_raw(raw_id)
    assert row is not None                      # строка на месте
    assert row["text"] == "про подрядчика"
    assert row["file_path"] is None
    assert "download" in row["error"]


async def test_transcription_failure_keeps_the_file(db: Database, tmp_path):
    bot = FakeBot()
    intake = Intake(db, tmp_path / "files", FakeTranscriber(boom=True))
    raw_id = await intake.accept(msg(message_id=9, voice=file("v1")), bot)

    row = db.get_raw(raw_id)
    assert Path(row["file_path"]).exists()
    assert row["transcript"] is None
    assert "whisper" in row["error"]


async def test_transcriber_off_leaves_transcript_empty(db: Database, tmp_path):
    bot = FakeBot()
    intake = Intake(db, tmp_path / "files", FakeTranscriber(available=False))
    raw_id = await intake.accept(msg(message_id=10, voice=file("v1")), bot)

    row = db.get_raw(raw_id)
    assert row["transcript"] is None
    assert row["error"] is None


async def test_repeat_of_the_same_message_is_ignored(db: Database, tmp_path):
    bot = FakeBot()
    intake = Intake(db, tmp_path / "files")
    first = await intake.accept(msg(message_id=11, text="дубль"), bot)
    second = await intake.accept(msg(message_id=11, text="дубль"), bot)

    assert first is not None
    assert second is None
    assert db.count_raw() == 1
