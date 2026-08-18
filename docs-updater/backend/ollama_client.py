"""Клиент локального Ollama. Единственные сетевые обращения сервиса.

Все ошибки превращаются в OllamaError с человеческим текстом и подсказкой-командой,
чтобы пользователь видел «запустите ollama serve», а не стектрейс.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*)\n\s*```\s*$", re.DOTALL)


class OllamaError(Exception):
    """Понятная пользователю ошибка обращения к Ollama."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def as_dict(self) -> dict[str, str]:
        return {"error": self.message, "hint": self.hint}


class OllamaClient:
    def __init__(self, host: str, timeout: float = 900.0) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout

    # --- служебное ---------------------------------------------------------

    def _not_running(self) -> OllamaError:
        return OllamaError(
            f"Не удалось подключиться к Ollama по адресу {self.host}. "
            "Похоже, локальный сервер не запущен.",
            hint="Запустите Ollama: `ollama serve` (или откройте приложение Ollama), затем повторите.",
        )

    def _model_missing(self, model: str) -> OllamaError:
        return OllamaError(
            f"Модель «{model}» не установлена в локальном Ollama.",
            hint=f"Установите её командой: `ollama pull {model}`",
        )

    def _post(self, path: str, payload: dict[str, Any], model: str) -> dict[str, Any]:
        try:
            response = httpx.post(f"{self.host}{path}", json=payload, timeout=self.timeout)
        except httpx.ConnectError as exc:
            raise self._not_running() from exc
        except httpx.ReadTimeout as exc:
            raise OllamaError(
                f"Ollama не ответил за {int(self.timeout)} с (модель «{model}»).",
                hint="Увеличьте `ollama.request_timeout` в config.yaml или возьмите модель поменьше.",
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ошибка обращения к Ollama: {exc}", hint="") from exc

        if response.status_code == 404:
            raise self._model_missing(model)
        if response.status_code >= 400:
            text = response.text.strip()
            if "not found" in text.lower():
                raise self._model_missing(model)
            raise OllamaError(
                f"Ollama вернул ошибку {response.status_code}: {text[:500]}",
                hint="Проверьте название модели в config.yaml и вывод команды `ollama list`.",
            )
        return response.json()

    # --- публичное API -----------------------------------------------------

    def list_models(self) -> list[str]:
        try:
            response = httpx.get(f"{self.host}/api/tags", timeout=10.0)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise self._not_running() from exc
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Ollama недоступен: {exc}",
                hint="Проверьте, что запущен `ollama serve`.",
            ) from exc
        return [item.get("name", "") for item in response.json().get("models", [])]

    def has_model(self, model: str) -> bool:
        installed = self.list_models()
        wanted = model.split(":")[0]
        return any(name == model or name.split(":")[0] == wanted for name in installed)

    def ensure_model(self, model: str) -> None:
        if not self.has_model(model):
            raise self._model_missing(model)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги пачкой. Сначала новый /api/embed, при отказе — старый /api/embeddings."""
        if not texts:
            return []
        try:
            data = self._post("/api/embed", {"model": model, "input": texts}, model)
            vectors = data.get("embeddings")
            if vectors:
                return vectors
        except OllamaError as exc:
            # Старые сборки Ollama не знают /api/embed — отличаем это от «нет модели».
            if "не установлена" in exc.message:
                raise
        vectors = []
        for text in texts:
            data = self._post("/api/embeddings", {"model": model, "prompt": text}, model)
            vectors.append(data.get("embedding", []))
        return vectors

    def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        num_ctx: int = 16384,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,  # отключаем «рассуждения» у qwen3 и подобных
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if system:
            payload["system"] = system
        try:
            data = self._post("/api/generate", payload, model)
        except OllamaError as exc:
            # Некоторые версии Ollama ругаются на параметр think у не-thinking моделей.
            if "think" in exc.message.lower():
                payload.pop("think", None)
                data = self._post("/api/generate", payload, model)
            else:
                raise
        return clean_model_output(data.get("response", ""))


def clean_model_output(text: str) -> str:
    """Убирает блоки рассуждений и обёртку в ``` вокруг всего ответа."""
    text = THINK_RE.sub("", text or "")
    text = text.replace("<think>", "").replace("</think>", "")
    text = text.strip()
    match = FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    return text
