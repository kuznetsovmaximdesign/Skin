"""Игрушечный Ollama для тестов: отвечает как настоящий, но без моделей и без сети наружу.

Эмбеддинги — детерминированный «мешок слов», так что похожие тексты дают похожие векторы.
"""

from __future__ import annotations

import json
import re
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSIONS = 96


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"\w+", text.lower()):
        vector[zlib.crc32(word.encode("utf-8")) % DIMENSIONS] += 1.0
    return vector


class FakeOllama:
    """Управляемый сервер: можно менять список моделей и ответ генерации."""

    def __init__(self, models: list[str] | None = None) -> None:
        self.models = models if models is not None else ["qwen3:latest", "bge-m3:latest"]
        self.generate_response: str | None = None
        self.fix_response: str | None = None
        # Необязательное преобразование присланного текста: (prompt, text) -> text.
        self.transform = None
        self.impact_response = "КЛАСС: дополнить\nПРИЧИНА: описан затронутый функционал"
        # Пауза между кусочками потока: позволяет тестам увидеть постепенный вывод.
        self.chunk_delay = 0.0
        self.review_response = (
            "- «Токен действует 120 минут.» — по гайду версии пишем полностью\n"
            "2. «Не более 10 запросов» — уточните единицу времени\n"
            "пояснение, которое не является замечанием"
        )
        self.requests: list[dict] = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = server
        self.port = server.server_address[1]
        self.host = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    def start(self) -> "FakeOllama":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # тишина в выводе тестов
                pass

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_stream(self, text: str) -> None:
                """Ответ построчно, как настоящий Ollama: NDJSON с полями response/done."""
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                step = max(1, len(text) // 8)
                for start in range(0, len(text), step):
                    chunk = json.dumps({"response": text[start : start + step], "done": False})
                    self.wfile.write(chunk.encode("utf-8") + b"\n")
                    self.wfile.flush()
                    if outer.chunk_delay:
                        time.sleep(outer.chunk_delay)
                self.wfile.write(json.dumps({"response": "", "done": True}).encode("utf-8") + b"\n")
                self.wfile.flush()

            def _known(self, model: str) -> bool:
                base = model.split(":")[0]
                return any(name == model or name.split(":")[0] == base for name in outer.models)

            def do_GET(self) -> None:
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": name} for name in outer.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append({"path": self.path, "payload": payload})
                model = payload.get("model", "")

                if not self._known(model):
                    self._send(404, {"error": f"model '{model}' not found"})
                    return

                if self.path == "/api/embed":
                    texts = payload.get("input") or []
                    if isinstance(texts, str):
                        texts = [texts]
                    self._send(200, {"embeddings": [embed_text(text) for text in texts]})
                elif self.path == "/api/embeddings":
                    self._send(200, {"embedding": embed_text(payload.get("prompt", ""))})
                elif self.path == "/api/generate":
                    text = outer.render(payload.get("prompt", ""))
                    if payload.get("stream"):
                        self._send_stream(text)
                    else:
                        self._send(200, {"response": text})
                else:
                    self._send(404, {"error": "not found"})

        return Handler

    def render(self, prompt: str) -> str:
        """По умолчанию возвращает присланный текст (документ или раздел) с одной правкой."""
        if "НАРУШЕНИЯ, НАЙДЕННЫЕ ПРОВЕРКОЙ" in prompt:
            if self.fix_response is not None:
                return self.fix_response
            # По умолчанию «модель» ничего не чинит и возвращает текст как есть.
            match = re.search(r"# ТЕКСТ\n\n(.*?)\n\n# НАРУШЕНИЯ", prompt, re.DOTALL)
            return match.group(1) if match else ""
        if "Классифицируй, что нужно сделать с этим документом" in prompt:
            return self.impact_response
        if "# ЗАДАНИЕ\n\nНапиши раздел" in prompt:
            found = re.search(r"Напиши раздел «([^»]+)» заголовком уровня (\d+)", prompt)
            if found:
                title, level = found.group(1), int(found.group(2))
                return f"{'#' * level} {title}\n\nТекст раздела по требованиям. [уточнить] точные лимиты."
        if "Напиши, что документирует этот документ" in prompt:
            title = re.search(r"# ДОКУМЕНТ: (.+)", prompt)
            name = title.group(1).strip() if title else "документ"
            return f"ОПИСАНИЕ: Документ описывает {name.lower()} и порядок работы с ним.\nСУЩНОСТИ: {name}, токен, лимиты"
        if "ПРОВЕРКА ПО ГАЙДУ" in prompt:
            return self.review_response
        if self.generate_response is not None:
            return self.generate_response
        match = re.search(
            r"# (?:ИСХОДНЫЙ ДОКУМЕНТ|РАЗДЕЛ, КОТОРЫЙ НУЖНО ОБНОВИТЬ).*?\n\n(.*?)\n\n# ЧТО ИЗМЕНИЛОСЬ",
            prompt,
            re.DOTALL,
        )
        source = match.group(1) if match else "# Пустой документ"
        if self.transform is not None:
            return self.transform(prompt, source)
        updated = source.replace("Токен действует 60 минут.", "Токен действует 120 минут.")
        return f"<think>рассуждения модели</think>\n{updated}\n"
