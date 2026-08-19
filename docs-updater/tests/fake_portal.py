"""Игрушечный портал справки для тестов импорта по ссылке.

Работает на localhost и отдаёт HTML со всей разметкой, которая встречается в справке:
заголовки, списки, врезки, таблицы, код, изображения.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<html><head><title>Настройка вебхуков</title>
<meta name="article-id" content="KB-9001">
<meta name="last-modified" content="2026-08-19">
</head><body>
<nav>Навигация, которую импортировать не нужно</nav>
<h1>Настройка вебхуков</h1>
<p>Документ описывает <b>настройку</b> вебхуков в <code>веб-интерфейсе</code>.</p>
<h2>Порядок действий</h2>
<p>Чтобы настроить вебхук:</p>
<ol><li>Откройте раздел <b>Настройки</b>.</li><li>Нажмите <b>Сохранить</b>.</li></ol>
<div class="alert alert-warning">Порт 443 должен быть открыт.</div>
<h2>Параметры</h2>
<table><tr><th>Параметр</th><th>Описание</th></tr>
<tr><td>url</td><td>Адрес приёмника</td></tr></table>
<pre><code>curl -X POST http://localhost/hook</code></pre>
<p>Подробнее — в <a href="/limits">разделе про лимиты</a>.</p>
<img src="/img/webhook.png" alt="Схема вебхука" title="Схема обмена">
<footer>Подвал сайта</footer>
</body></html>"""


class FakePortal:
    def __init__(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = server
        self.port = server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.requests: list[str] = []
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    def start(self) -> "FakePortal":
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

            def do_GET(self) -> None:
                outer.requests.append(self.path)
                if self.path.startswith("/help"):
                    body = PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        return Handler
