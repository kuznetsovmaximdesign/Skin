"""Конфигурация. Секреты живут в отдельном файле с правами 600, не в исходниках."""

from __future__ import annotations

import logging
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.toml"


class ConfigError(Exception):
    """Конфиг отсутствует или заполнен не полностью."""


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool = True
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"


@dataclass(frozen=True)
class HeartbeatConfig:
    url: str = ""
    interval_seconds: int = 300


@dataclass(frozen=True)
class Config:
    token: str
    owner_id: int
    db_path: Path
    files_dir: Path
    log_path: Path
    log_level: str
    voice: VoiceConfig
    heartbeat: HeartbeatConfig

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        cfg_path = Path(path or os.environ.get("LIFE_BOT_CONFIG", DEFAULT_CONFIG_PATH))
        if not cfg_path.exists():
            raise ConfigError(f"нет файла конфигурации: {cfg_path}")

        _warn_on_loose_permissions(cfg_path)

        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)

        telegram = data.get("telegram", {})
        token = str(telegram.get("token", "")).strip()
        if not token or token.endswith("ЗАМЕНИТЬ"):
            raise ConfigError("telegram.token не заполнен")

        owner_id = int(telegram.get("owner_id", 0) or 0)
        if owner_id <= 0:
            raise ConfigError("telegram.owner_id не заполнен")

        paths = data.get("paths", {})
        base = cfg_path.parent.resolve()
        voice = data.get("voice", {})
        heartbeat = data.get("heartbeat", {})
        log_section = data.get("log", {})

        return cls(
            token=token,
            owner_id=owner_id,
            db_path=_resolve(base, paths.get("db", "var/life_bot.db")),
            files_dir=_resolve(base, paths.get("files", "var/files")),
            log_path=_resolve(base, paths.get("log", "var/life_bot.log")),
            log_level=str(log_section.get("level", "INFO")).upper(),
            voice=VoiceConfig(
                enabled=bool(voice.get("enabled", True)),
                model=str(voice.get("model", "small")),
                device=str(voice.get("device", "cpu")),
                compute_type=str(voice.get("compute_type", "int8")),
            ),
            heartbeat=HeartbeatConfig(
                url=str(heartbeat.get("url", "")).strip(),
                interval_seconds=int(heartbeat.get("interval_seconds", 300)),
            ),
        )


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path)


def _warn_on_loose_permissions(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        log.warning("конфиг %s открыт для группы и остальных (%o), нужно 600", path, mode)
