"""Поддельный Telegram: запоминает отправленное, ничего не шлёт в сеть."""

from pathlib import Path
from types import SimpleNamespace


class FakeBot:
    def __init__(self):
        self.sent = []          # (chat_id, text, есть ли кнопки)
        self.edited = []        # (message_id, text)
        self.pinned = []
        self.reactions = []
        self._next_id = 1000

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self._next_id += 1
        self.sent.append((chat_id, text, reply_markup is not None))
        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kwargs):
        self.edited.append((message_id, text))
        return SimpleNamespace(message_id=message_id)

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        self.pinned.append(message_id)

    async def set_message_reaction(self, chat_id, message_id, reaction, **kwargs):
        self.reactions.append(message_id)

    async def download(self, file_id, destination):
        Path(destination).write_bytes(b"data")

    @property
    def texts(self):
        return [text for _, text, _ in self.sent]


class FakeMessage:
    """Только то, чем пользуются приём и обработчики."""

    def __init__(self, text=None, message_id=1, chat_id=100):
        self.message_id = message_id
        self.text = text
        self.caption = None
        self.voice = None
        self.audio = None
        self.video_note = None
        self.photo = None
        self.document = None
        self.forward_origin = None
        self.forward_from = None
        self.forward_from_chat = None
        self.forward_sender_name = None
        self.forward_date = None
        self.chat = SimpleNamespace(id=chat_id)
        self.replies = []

    async def reply(self, text, reply_markup=None, **kwargs):
        self.replies.append((text, reply_markup))
        return SimpleNamespace(message_id=self.message_id + 500)


class FakeCallback:
    def __init__(self, data, message_id=2000):
        self.data = data
        self.answered = 0
        self.message = SimpleNamespace(
            message_id=message_id, edit_text=self._edit, text=None
        )
        self.edits = []

    async def _edit(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))
        self.message.text = text

    async def answer(self, *args, **kwargs):
        self.answered += 1

    @property
    def last_text(self):
        return self.edits[-1][0] if self.edits else None

    @property
    def last_markup(self):
        return self.edits[-1][1] if self.edits else None
