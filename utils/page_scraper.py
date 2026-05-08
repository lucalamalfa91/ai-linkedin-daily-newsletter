"""Fetches a URL and returns clean readable text, stripping HTML tags."""

import logging
import re
from html.parser import HTMLParser

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 15
_MAX_BYTES = 524288   # 512 KB read limit
_MAX_CHARS = 8000     # chars passed to Claude


class _TextExtractor(HTMLParser):
    """Strips HTML tags; skips script/style/nav/footer blocks."""

    _SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            self._skip_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            if self._skip_depth == 0:
                self._skip_tag = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    @property
    def text(self) -> str:
        raw = " ".join(self._parts)
        # Collapse runs of whitespace
        return re.sub(r"\s{3,}", "\n\n", raw)


def fetch_page_text(url: str, max_chars: int = _MAX_CHARS) -> str:
    """Fetch `url` and return up to `max_chars` of clean readable text.

    For .md / plain-text URLs returns raw content directly.
    Returns empty string on any failure (caller should handle gracefully).
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ai-coding-digest/1.0)"},
            timeout=_TIMEOUT,
            stream=True,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        # Read up to _MAX_BYTES
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=32768):
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_BYTES:
                break
        raw = b"".join(chunks).decode("utf-8", errors="replace")

        # Plain text / Markdown: return as-is
        if "text/plain" in content_type or url.endswith(".md"):
            return raw[:max_chars]

        # HTML: strip tags
        parser = _TextExtractor()
        try:
            parser.feed(raw)
        except Exception:
            pass
        return parser.text[:max_chars]

    except Exception as exc:
        log.warning("page_scraper: failed to fetch %s: %s", url, exc)
        return ""
