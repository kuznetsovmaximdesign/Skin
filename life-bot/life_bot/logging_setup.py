"""Логи: файл с ротацией плюс stderr для journalctl."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup(log_path: Path, level: str = "INFO") -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(),
    ]
    for handler in handlers:
        handler.setFormatter(logging.Formatter(FORMAT))
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
