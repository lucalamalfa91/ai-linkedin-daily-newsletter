"""Extract the primary external source a blogger is reacting to.

When a blogger writes "My take on the new GPT-5 release...", we want
the GPT-5 announcement URL — not the blogger's post URL.

Flow per item:
  1. Scan RSS summary for external URLs (cheap, no LLM)
  2. Ask Claude Haiku to identify the primary source using title + summary
  3. If not found: fetch full page text and retry with Haiku
  4. If still not found: return None (use blogger post as-is)
"""

import json
import logging
import re
from urllib.parse import urlparse

import anthropic

from utils.json_utils import strip_json_fences
from utils.page_scraper import fetch_page_text
from utils.url_utils import is_valid_url, normalize_url

log = logging.getLogger(__name__)

_SYSTEM = """\
You analyze posts written by AI bloggers and commentators.
Your task: identify the PRIMARY external source they are reacting to or discussing.

A primary source is the original article, paper, model release, or announcement that the blogger is commenting on.
It must be from a DIFFERENT website than the blogger's own domain.

Return ONLY valid JSON — no markdown fences:
  {"found": true, "url": "https://...", "title": "...", "source_name": "..."}
  or
  {"found": false}

Rules:
- "found": true only if there is ONE clear primary source the post is about
- If the post IS the original analysis (no primary source), return {"found": false}
- The url must be from a different domain than the blogger
- Prefer: official announcements, arXiv papers, product pages, research blog posts
- source_name: the organization or publication name (e.g. "OpenAI", "arXiv", "Nature")
- Never invent a URL — only return URLs explicitly present in the content
"""


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _extract_urls(text: str) -> list[str]:
    return re.findall(r'https?://[^\s"\'<>)\]]+', text)


def extract_original_source(item: dict, client: anthropic.Anthropic) -> dict | None:
    """Return {url, title, source_name} of the original source, or None."""
    blogger_domain = _domain(item.get("link", ""))
    summary = item.get("summary", "")

    # Quick scan: find external URLs already in the RSS summary
    candidate_urls = [
        u for u in _extract_urls(summary)
        if blogger_domain not in u and is_valid_url(normalize_url(u))
    ]

    user_msg = (
        f"Blogger: {item.get('source', '')}\n"
        f"Post title: {item.get('title', '')}\n"
        f"Post summary: {summary[:600]}"
    )
    if candidate_urls:
        user_msg += f"\n\nURLs found in summary: {chr(10).join(candidate_urls[:5])}"

    result = _ask_haiku(user_msg, blogger_domain, client)
    if result:
        log.info("Source extracted from summary for '%s' → %s", item.get("title", "")[:60], result["url"])
        return result

    # Fallback: fetch full page and retry
    page_text = fetch_page_text(item.get("link", ""))
    if not page_text:
        return None

    page_urls = [
        u for u in _extract_urls(page_text)
        if blogger_domain not in u and is_valid_url(normalize_url(u))
    ]
    user_msg_full = (
        f"Blogger: {item.get('source', '')}\n"
        f"Post title: {item.get('title', '')}\n"
        f"Post content (excerpt):\n{page_text[:1800]}"
    )
    if page_urls:
        user_msg_full += f"\n\nURLs found in post: {chr(10).join(page_urls[:8])}"

    result = _ask_haiku(user_msg_full, blogger_domain, client)
    if result:
        log.info("Source extracted from full page for '%s' → %s", item.get("title", "")[:60], result["url"])
    else:
        log.debug("No primary source found for '%s' — using blogger post", item.get("title", "")[:60])
    return result


def _ask_haiku(user_msg: str, blogger_domain: str, client: anthropic.Anthropic) -> dict | None:
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            temperature=0,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = strip_json_fences(msg.content[0].text)
        data = json.loads(raw)
        if not data.get("found"):
            return None
        url = normalize_url(data.get("url", ""))
        if not is_valid_url(url) or blogger_domain in url:
            return None
        return {
            "url": url,
            "title": data.get("title", "").strip(),
            "source_name": data.get("source_name", "").strip(),
        }
    except Exception as exc:
        log.debug("Haiku source extraction error: %s", exc)
        return None
