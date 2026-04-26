import logging
from datetime import datetime, timedelta, timezone

import feedparser

from config import RSS_FEEDS
from utils.url_utils import normalize_url

log = logging.getLogger(__name__)


def fetch_feeds(days: int = 7) -> list[dict]:
    """Fetch all RSS feeds and return items from the last `days` days, sorted newest-first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[dict] = []

    for source, url in RSS_FEEDS.items():
        try:
            log.info("Fetching %s ...", source)
            feed = feedparser.parse(
                url,
                request_headers={"User-Agent": "Mozilla/5.0 (compatible; ai-post-bot/1.0)"},
            )
            for entry in feed.entries:
                pub_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
                if not pub_tuple:
                    continue
                pub_dt = datetime(*pub_tuple[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
                link = normalize_url(entry.get("link", ""))
                items.append({
                    "source": source,
                    "title": entry.get("title", "").strip(),
                    "link": link,
                    "summary": (entry.get("summary", "") or "")[:400],
                    "published": pub_dt.isoformat(),
                })
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", source, exc)

    items.sort(key=lambda x: x["published"], reverse=True)
    log.info("Found %d items in the last %d days", len(items), days)
    return items
