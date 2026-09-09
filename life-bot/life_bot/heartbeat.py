"""Heartbeat на healthchecks.io.

Упавший бот не может сообщить о себе сам — контроль только внешний. Пока
процесс жив, он раз в N секунд стучится по адресу из конфига. Перестал
стучаться — внешний сервис поднимает тревогу.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, url: str | None, interval: int = 300) -> None:
        self.url = (url or "").strip()
        self.interval = max(30, int(interval))
        self._task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    async def ping(self, suffix: str = "") -> bool:
        """Один стук. Сбой сети не считается ошибкой бота — только пишется в лог."""
        if not self.enabled:
            return False
        import aiohttp

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.url + suffix) as response:
                    return response.status < 400
        except Exception as exc:
            log.warning("heartbeat не ушёл: %s", exc)
            return False

    async def _loop(self) -> None:
        while True:
            await self.ping()
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if not self.enabled:
            log.info("heartbeat выключен: адрес не задан")
            return
        self._task = asyncio.create_task(self._loop(), name="heartbeat")
        log.info("heartbeat каждые %s с", self.interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
