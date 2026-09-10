"""Расшифровка голоса локальным faster-whisper.

Модель грузится лениво, при первом голосовом. Библиотеки нет или модель не
поднялась — расшифровки просто не будет, сообщение всё равно сохранено.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(
        self,
        *,
        enabled: bool = True,
        model: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "ru",
    ) -> None:
        self.enabled = enabled
        self.model_size = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        self._broken = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.enabled and not self._broken

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                log.info("гружу whisper %s (%s, %s)", self.model_size, self.device, self.compute_type)
                self._model = WhisperModel(
                    self.model_size, device=self.device, compute_type=self.compute_type
                )
        return self._model

    def transcribe(self, path: Path | str) -> str:
        """Возвращает текст. Блокирующий вызов, запускать через to_thread."""
        if not self.available:
            return ""
        try:
            model = self._load()
        except Exception:
            self._broken = True
            log.exception("whisper не поднялся, расшифровка отключена до перезапуска")
            return ""
        segments, _info = model.transcribe(str(path), language=self.language, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
