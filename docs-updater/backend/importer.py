"""Импорт справочной статьи по ссылке: HTML → Markdown.

Это единственное место, где сервис может обратиться не к localhost. Поэтому:

- по умолчанию импорт выключен;
- работает только со списком разрешённых адресов из config.yaml;
- запускается вручную пользователем, ничего не делает сам;
- наружу не отправляет ничего, кроме самого запроса страницы: ни документов, ни требований;
- каждое обращение пишется в журнал аудита.

Разметка распознаётся встроенным конвертером (стандартная библиотека, без зависимостей):
заголовки, списки, таблицы, код, цитаты и врезки, ссылки, изображения с alt-текстом.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "blockquote", "pre", "table"}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
ADMONITION_HINTS = {
    "note": "NOTE",
    "info": "NOTE",
    "tip": "TIP",
    "warning": "WARNING",
    "warn": "WARNING",
    "caution": "CAUTION",
    "important": "IMPORTANT",
    "example": "EXAMPLE",
}
SPACES_RE = re.compile(r"[ \t]+")
BLANKS_RE = re.compile(r"\n{3,}")


class HtmlToMarkdown(HTMLParser):
    """Небольшой конвертер HTML → Markdown: только то, что встречается в справке."""

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.skip_depth = 0
        self.heading: int | None = None
        self.list_stack: list[dict[str, Any]] = []
        self.in_pre = False
        self.pre_lines: list[str] = []
        self.link: str = ""
        self.link_text: list[str] = []
        self.quote_type: str = ""
        self.in_quote = False
        self.table: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False

    # --- служебное ---------------------------------------------------------

    def emit(self, text: str) -> None:
        if self.cell is not None:
            self.cell.append(text)
        elif self.link:
            self.link_text.append(text)
        else:
            self.parts.append(text)

    def newline(self, count: int = 1) -> None:
        self.emit("\n" * count)

    @staticmethod
    def classes(attrs: list[tuple[str, str | None]]) -> str:
        values = dict(attrs)
        return " ".join(
            str(values.get(key) or "") for key in ("class", "data-type", "role", "id")
        ).lower()

    # --- разбор ------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = str(values.get("name") or values.get("property") or "").lower()
            content = str(values.get("content") or "")
            if name and content:
                self.meta[name] = content
        elif tag in HEADING_TAGS:
            self.newline(2)
            self.heading = HEADING_TAGS[tag]
            self.emit("#" * self.heading + " ")
        elif tag in {"ul", "ol"}:
            self.list_stack.append({"ordered": tag == "ol", "index": 0})
            self.newline()
        elif tag == "li":
            self.newline()
            if self.list_stack:
                level = len(self.list_stack) - 1
                current = self.list_stack[-1]
                current["index"] += 1
                marker = f"{current['index']}." if current["ordered"] else "-"
                self.emit("  " * level + marker + " ")
        elif tag == "pre":
            self.in_pre = True
            self.pre_lines = []
        elif tag == "code" and not self.in_pre:
            self.emit("`")
        elif tag in {"b", "strong"}:
            self.emit("**")
        elif tag in {"i", "em"}:
            self.emit("*")
        elif tag == "br":
            self.newline()
        elif tag == "a":
            href = str(values.get("href") or "")
            if href and not href.startswith(("#", "javascript:")):
                self.link = urljoin(self.base_url, href) if self.base_url else href
                self.link_text = []
        elif tag == "img":
            alt = str(values.get("alt") or "").strip()
            src = urljoin(self.base_url, str(values.get("src") or "")) if self.base_url else str(values.get("src") or "")
            title = str(values.get("title") or "").strip()
            self.newline(2)
            self.emit(f"![{alt}]({src}" + (f' "{title}"' if title else "") + ")")
            self.newline(2)
        elif tag == "blockquote":
            self.in_quote = True
            marker = self.classes(attrs)
            self.quote_type = next(
                (value for key, value in ADMONITION_HINTS.items() if key in marker), ""
            )
            self.newline(2)
            if self.quote_type:
                self.emit(f"> [!{self.quote_type}]\n")
            self.emit("> ")
        elif tag == "div" and not self.in_quote:
            marker = self.classes(attrs)
            kind = next((value for key, value in ADMONITION_HINTS.items() if key in marker), "")
            if kind:
                # Врезка размечена классом — переносим её типом, а не цветом.
                self.in_quote = True
                self.quote_type = kind
                self.newline(2)
                self.emit(f"> [!{kind}]\n> ")
        elif tag == "table":
            self.table = []
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
        elif tag in BLOCK_TAGS:
            self.newline()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return

        if tag == "title":
            self._in_title = False
        elif tag in HEADING_TAGS:
            self.heading = None
            self.newline(2)
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.newline()
        elif tag == "pre":
            self.in_pre = False
            body = "".join(self.pre_lines).strip("\n")
            self.newline(2)
            self.emit(f"```\n{body}\n```")
            self.newline(2)
        elif tag == "code" and not self.in_pre:
            self.emit("`")
        elif tag in {"b", "strong"}:
            self.emit("**")
        elif tag in {"i", "em"}:
            self.emit("*")
        elif tag == "a" and self.link:
            text = SPACES_RE.sub(" ", "".join(self.link_text)).strip()
            href, self.link, self.link_text = self.link, "", []
            self.emit(f"[{text}]({href})" if text else href)
        elif tag in {"blockquote", "div"} and self.in_quote:
            self.in_quote = False
            self.quote_type = ""
            self.newline(2)
        elif tag in {"td", "th"} and self.cell is not None:
            text = SPACES_RE.sub(" ", "".join(self.cell)).strip().replace("|", "\\|")
            if self.row is not None:
                self.row.append(text)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            self.flush_table()
        elif tag == "li":
            pass  # разделитель уже поставлен в начале пункта: список остаётся плотным
        elif tag in BLOCK_TAGS:
            self.newline()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self._in_title:
            self.title = (self.title + data).strip()
            return
        if self.in_pre:
            self.pre_lines.append(data)
            return

        text = SPACES_RE.sub(" ", data.replace("\r", ""))
        if not text.strip():
            if text and self.parts and not self.parts[-1].endswith((" ", "\n")):
                self.emit(" ")
            return
        if self.in_quote:
            text = text.replace("\n", "\n> ")
        self.emit(text)

    def flush_table(self) -> None:
        rows = [row for row in self.table if row]
        self.table = []
        if not rows:
            return
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        head, body = rows[0], rows[1:]
        self.newline(2)
        self.emit("| " + " | ".join(head) + " |\n")
        self.emit("|" + "|".join([" --- "] * width) + "|\n")
        for row in body:
            self.emit("| " + " | ".join(row) + " |\n")
        self.newline()

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = BLANKS_RE.sub("\n\n", text)
        text = re.sub(r"\n> \n", "\n>\n", text)
        return text.strip() + "\n"


# --- сетевой доступ ---------------------------------------------------------


class ImportError_(Exception):
    """Понятная ошибка импорта: показывается пользователю как есть."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


def settings(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("import_web", {}) or {}


def allowed_hosts(config: dict[str, Any]) -> list[str]:
    return [str(item).lower() for item in settings(config).get("allowed_hosts", [])]


def check_url(config: dict[str, Any], url: str) -> str:
    """Проверяет, что адрес разрешён. Возвращает хост."""
    if not settings(config).get("enabled", False):
        raise ImportError_(
            "Импорт по ссылке выключен.",
            hint="Включите import_web.enabled и перечислите разрешённые адреса в config.yaml.",
        )

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImportError_(f"Неподдерживаемый адрес: {url}", hint="Нужна ссылка http или https.")

    host = (parsed.hostname or "").lower()
    permitted = allowed_hosts(config)
    if not permitted:
        raise ImportError_(
            "Не задан список разрешённых адресов.",
            hint="Перечислите хосты справки в import_web.allowed_hosts.",
        )
    if not any(host == item or host.endswith("." + item) for item in permitted):
        raise ImportError_(
            f"Адрес «{host}» не в списке разрешённых.",
            hint="Разрешённые: " + ", ".join(permitted),
        )
    return host


def fetch(config: dict[str, Any], url: str) -> str:
    """Скачивает страницу. Наружу уходит только запрос — ни документов, ни требований."""
    check_url(config, url)
    timeout = float(settings(config).get("timeout", 30))
    headers = {"User-Agent": str(settings(config).get("user_agent", "docs-updater/1.0 (local)"))}
    try:
        response = httpx.get(url, timeout=timeout, headers=headers, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ImportError_(f"Не удалось получить страницу: {error}", hint="Проверьте адрес и доступность портала.")
    return response.text


def convert(html: str, url: str = "") -> dict[str, Any]:
    """HTML → Markdown плюс метаданные страницы."""
    parser = HtmlToMarkdown(base_url=url)
    parser.feed(html)
    parser.close()

    markdown = parser.markdown()
    title = parser.title or next(
        (line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")), ""
    )
    if title and not markdown.lstrip().startswith("#"):
        markdown = f"# {title}\n\n{markdown}"

    meta = parser.meta
    return {
        "markdown": markdown,
        "title": title,
        "meta": {
            "article_id": meta.get("article-id") or meta.get("articleid") or "",
            "updated": meta.get("last-modified") or meta.get("article:modified_time") or "",
            "locale": meta.get("og:locale") or meta.get("language") or "",
            "description": meta.get("description", ""),
        },
        "source_url": url,
    }


def import_url(config: dict[str, Any], url: str) -> dict[str, Any]:
    """Скачивает статью и превращает её в Markdown. Ничего не сохраняет."""
    html = fetch(config, url)
    result = convert(html, url)
    result["chars"] = len(result["markdown"])
    return result
