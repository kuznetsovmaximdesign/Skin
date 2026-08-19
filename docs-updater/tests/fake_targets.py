"""Игрушечные Confluence и портал для тестов публикации.

Работают на localhost, запоминают созданные страницы и версии — так проверяется
идемпотентность: повторная публикация обновляет ту же страницу, а не плодит дубликаты.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeTargets:
    def __init__(self) -> None:
        self.pages: dict[str, dict] = {}
        self.articles: dict[str, dict] = {}
        self.requests: list[dict] = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = server
        self.port = server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    def start(self) -> "FakeTargets":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _read(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                return json.loads(self.rfile.read(length) or b"{}")

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                payload = self._read()
                outer.requests.append({"method": "POST", "path": self.path, "payload": payload,
                                       "auth": self.headers.get("Authorization", "")})
                if self.path.endswith("/rest/api/content"):
                    page_id = f"page-{len(outer.pages) + 1}"
                    outer.pages[page_id] = {**payload, "version": {"number": 1}}
                    self._send(200, {"id": page_id, "version": {"number": 1}})
                elif self.path.endswith("/api/articles"):
                    article_id = f"art-{len(outer.articles) + 1}"
                    outer.articles[article_id] = {**payload, "version": 1}
                    self._send(200, {"id": article_id, "version": 1})
                else:
                    self._send(404, {"error": "not found"})

            def do_PUT(self) -> None:
                payload = self._read()
                outer.requests.append({"method": "PUT", "path": self.path, "payload": payload,
                                       "auth": self.headers.get("Authorization", "")})
                identifier = self.path.rstrip("/").split("/")[-1]
                if "/rest/api/content/" in self.path and identifier in outer.pages:
                    version = payload.get("version", {}).get("number", 2)
                    outer.pages[identifier] = {**payload, "version": {"number": version}}
                    self._send(200, {"id": identifier, "version": {"number": version}})
                elif "/api/articles/" in self.path and identifier in outer.articles:
                    version = outer.articles[identifier].get("version", 1) + 1
                    outer.articles[identifier] = {**payload, "version": version}
                    self._send(200, {"id": identifier, "version": version})
                else:
                    self._send(404, {"error": "not found"})

        return Handler
