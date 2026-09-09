"""Heartbeat на healthchecks.io.

Упавший бот не может сообщить о себе сам — контроль только внешний. Раз в N
секунд бот стучится по адресу из конфига, но лишь убедившись, что Telegram
отвечает: живой процесс без связи с Telegram — это молчащий бот, и стучать
за него «всё хорошо» нельзя.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, url: str | None, interval: int = 300, check=None) -> None:
        self.url = (url or "").strip()
        self.interval = max(30, int(interval))
        self.check = check      # проверка живости связи с Telegram
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
            await self.beat()
            await asyncio.sleep(self.interval)

    async def beat(self) -> bool:
        """Стук только при живой связи с Telegram.

        Процесс может быть жив, а Telegram недоступен — тогда бот молчит,
        и стучать «всё хорошо» нельзя: внешний контроль перестанет быть
        контролем. Проверка не прошла — пропускаем такт, и healthchecks.io
        сам поднимет тревогу.
        """
        if self.check is not None:
            try:
                await self.check()
            except Exception as exc:
                log.warning("связь с Telegram не подтверждена, стук пропущен: %s", exc)
                return False
        return await self.ping()

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
