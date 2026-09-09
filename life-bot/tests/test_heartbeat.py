"""Heartbeat: выключен без адреса, сбой сети не роняет бота."""

import asyncio

from life_bot.config import Config
from life_bot.heartbeat import Heartbeat


def test_disabled_without_url():
    assert not Heartbeat("").enabled
    assert not Heartbeat(None).enabled
    assert Heartbeat("https://hc-ping.com/abc").enabled


def test_interval_has_a_floor():
    assert Heartbeat("https://x", interval=5).interval == 30
    assert Heartbeat("https://x", interval=600).interval == 600


async def test_ping_without_url_does_nothing():
    assert await Heartbeat("").ping() is False


async def test_network_failure_is_swallowed():
    # Адрес заведомо недостижим: ping возвращает False, исключение не всплывает.
    beat = Heartbeat("http://127.0.0.1:9/never", interval=30)
    assert await beat.ping() is False


async def test_start_and_stop_are_safe_when_disabled():
    beat = Heartbeat("")
    beat.start()
    await beat.stop()


async def test_loop_stops_on_request(monkeypatch):
    beat = Heartbeat("https://example.invalid/ping", interval=30)
    pings = []

    async def fake_ping(suffix=""):
        pings.append(suffix)
        return True

    monkeypatch.setattr(beat, "ping", fake_ping)
    beat.start()
    await asyncio.sleep(0.05)
    await beat.stop()
    assert pings == [""]


def test_config_reads_heartbeat(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[telegram]\ntoken = "1:a"\nowner_id = 5\n'
        '[heartbeat]\nurl = "https://hc-ping.com/uuid"\ninterval_seconds = 120\n',
        encoding="utf-8",
    )
    path.chmod(0o600)
    config = Config.load(path)
    assert config.heartbeat.url == "https://hc-ping.com/uuid"
    assert config.heartbeat.interval_seconds == 120


def test_config_heartbeat_defaults_to_off(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\ntoken = "1:a"\nowner_id = 5\n', encoding="utf-8")
    path.chmod(0o600)
    config = Config.load(path)
    assert config.heartbeat.url == ""
    assert config.heartbeat.interval_seconds == 300
