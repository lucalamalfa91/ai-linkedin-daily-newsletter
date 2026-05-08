"""Lightweight scraper for Cursor's changelog page (no RSS available)."""

import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

import requests

log = logging.getLogger(__name__)

_CHANGELOG_URL = "https://www.cursor.com/changelog"
_TIMEOUT = 10


class _ChangelogParser(HTMLParser):
    """Extracts changelog entries from cursor.com/changelog."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[dict] = []
        self._in_article = False
        self._depth = 0
        self._current: dict | None = None
        self._capture_title = False
        self._capture_date = False
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr_map = dict(attrs)
        cls = attr_map.get("class", "")

        if tag == "article":
            self._in_article = True
            self._depth = 0
            self._current = {"title": "", "date": "", "summary": ""}
            return

        if not self._in_article or self._current is None:
            return

        self._depth += 1

        if tag in ("h1", "h2", "h3") and not self._current["title"]:
            self._capture_title = True
            self._buf = ""

        if tag == "time":
            dt_val = attr_map.get("datetime", "")
            if dt_val:
                self._current["date"] = dt_val
            else:
                self._capture_date = True
                self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self._in_article:
            if self._current and self._current.get("title"):
                self._entries.append(self._current)
            self._in_article = False
            self._current = None
            return

        if self._capture_title and tag in ("h1", "h2", "h3"):
            if self._current:
                self._current["title"] = self._buf.strip()
            self._capture_title = False

        if self._capture_date and tag == "time":
            if self._current and not self._current["date"]:
                self._current["date"] = self._buf.strip()
            self._capture_date = False

    def handle_data(self, data: str) -> None:
        if self._capture_title or self._capture_date:
            self._buf += data

    @property
    def entries(self) -> list[dict]:
        return self._entries


def _parse_date(raw: str) -> str:
    """Try to parse a date string and return ISO 8601, or return raw if unparseable."""
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return raw


def fetch_cursor_changelog(limit: int = 5) -> list[dict]:
    """Scrape Cursor changelog and return up to `limit` recent entries as feed-agent-compatible dicts."""
    try:
        resp = requests.get(
            _CHANGELOG_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ai-post-bot/1.0)"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.warning("cursor_scraper: failed to fetch changelog: %s", exc)
        return []

    parser = _ChangelogParser()
    try:
        # Read only first 512 KB to keep it lightweight
        parser.feed(resp.text[:524288])
    except Exception as exc:
        log.warning("cursor_scraper: parse error: %s", exc)
        return []

    items = []
    for entry in parser.entries[:limit]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        published = _parse_date(entry.get("date", ""))
        items.append({
            "source": "Cursor",
            "title": title,
            "link": _CHANGELOG_URL,
            "summary": entry.get("summary", "")[:400],
            "published": published,
        })

    log.info("cursor_scraper: found %d entries", len(items))
    return items
