"""Extracts recent changelog items from a scraped product page using Claude Haiku."""

import json
import logging
from datetime import datetime, timezone

import anthropic

log = logging.getLogger(__name__)

_SYSTEM = (
    "Extract recent changelog/release items from a product page text. "
    "Reply ONLY with valid JSON — no markdown fences, no extra text."
)

_PROMPT = """\
Product: {source}
Page URL: {url}
Page text (truncated):
---
{text}
---

Extract the 2 most recent updates/releases from this page.
For each item return:
  - title: short descriptive title (max 12 words)
  - summary: 1-2 sentences describing what changed
  - date: ISO date string if visible, else ""

Return JSON: {{"items": [{{"title": "...", "summary": "...", "date": "..."}}]}}
If no clear changelog items are found, return {{"items": []}}"""


def extract_changelog_items(
    page_text: str,
    source_name: str,
    source_url: str,
    client: anthropic.Anthropic,
) -> list[dict]:
    """Ask Claude Haiku to pull recent release items from scraped page text.

    Returns feed-agent-compatible dicts: {source, title, link, summary, published}.
    """
    if not page_text.strip():
        log.warning("changelog_agent: empty page text for %s", source_name)
        return []

    prompt = _PROMPT.format(source=source_name, url=source_url, text=page_text[:6000])

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            temperature=0,
            system=_SYSTEM,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + msg.content[0].text.strip()
        data = json.loads(raw)
        items = data.get("items", [])
    except Exception as exc:
        log.warning("changelog_agent: LLM failed for %s: %s", source_name, exc)
        return []

    today = datetime.now(timezone.utc).isoformat()
    results = []
    for item in items:
        title = item.get("title", "").strip()
        if not title:
            continue
        results.append({
            "source": source_name,
            "title": title,
            "link": source_url,
            "summary": item.get("summary", "").strip(),
            "published": item.get("date") or today,
        })

    log.info("changelog_agent: %d items from %s", len(results), source_name)
    return results
