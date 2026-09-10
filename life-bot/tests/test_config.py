"""Конфигурация: читается из файла, а не из кода."""

import logging

import pytest

from life_bot.config import Config, ConfigError

GOOD = """
[telegram]
token = "123:abc"
owner_id = 555

[paths]
db = "var/bot.db"
files = "var/files"
log = "var/bot.log"

[voice]
enabled = false
model = "medium"

[log]
level = "debug"
"""


def write(tmp_path, body, mode=0o600):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def test_load(tmp_path):
    config = Config.load(write(tmp_path, GOOD))
    assert config.token == "123:abc"
    assert config.owner_id == 555
    assert config.db_path == tmp_path / "var/bot.db"
    assert config.files_dir == tmp_path / "var/files"
    assert config.log_level == "DEBUG"
    assert config.voice.enabled is False
    assert config.voice.model == "medium"
    assert config.voice.compute_type == "int8"  # значение по умолчанию


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        Config.load(tmp_path / "нет.toml")


def test_example_config_is_rejected_until_filled(tmp_path):
    body = '[telegram]\ntoken = "123456:ЗАМЕНИТЬ"\nowner_id = 1\n'
    with pytest.raises(ConfigError, match="token"):
        Config.load(write(tmp_path, body))


def test_owner_required(tmp_path):
    body = '[telegram]\ntoken = "123:abc"\n'
    with pytest.raises(ConfigError, match="owner_id"):
        Config.load(write(tmp_path, body))


def test_loose_permissions_are_reported(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        Config.load(write(tmp_path, GOOD, mode=0o644))
    assert "600" in caplog.text


def test_env_variable_is_used(tmp_path, monkeypatch):
    path = write(tmp_path, GOOD)
    monkeypatch.setenv("LIFE_BOT_CONFIG", str(path))
    assert Config.load().owner_id == 555


def test_example_file_matches_the_loader():
    """Пример конфига должен разбираться и содержать все ключи, что читает код."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads(Path("config.example.toml").read_text(encoding="utf-8"))
    assert set(data) == {"telegram", "paths", "voice", "heartbeat", "log"}
    assert set(data["paths"]) == {"db", "files", "log"}
    assert set(data["voice"]) == {"enabled", "model", "device", "compute_type"}
    assert set(data["heartbeat"]) == {"url", "interval_seconds"}
