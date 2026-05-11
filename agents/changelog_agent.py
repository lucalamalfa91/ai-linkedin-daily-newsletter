"""Extracts recent changelog items from a scraped product page using Claude Haiku."""

import json
import logging
from datetime import datetime, timezone

import anthropic

from utils.json_utils import strip_json_fences

log = logging.getLogger(__name__)

_SYSTEM = (
    "You extract concrete, newsworthy release items from a product changelog or 'what's new' page. "
    "Focus only on entries that describe a specific, tangible change — a new feature, a meaningful "
    "behavioral fix, or a measurable improvement. Skip generic announcements, blog-post links, "
    "partnership news, or vague performance claims without detail. "
    "Reply ONLY with valid JSON — no markdown fences, no extra text."
)

_PROMPT = """\
Product: {source}
Page URL: {url}
Page text (truncated to first 6 000 chars):
---
{text}
---

Extract the 2-3 most recent, CONCRETE changelog entries from this page.

For each entry:
  - title: specific name of the feature or change (max 12 words; avoid generic phrases like
    "improvements" or "updates" — name the thing)
  - what_changed: 1-2 sentences — exactly what the product does now that it didn't before,
    or what problem was fixed. Include any numbers, before/after comparison, or scope
    (e.g. "max context window raised from 128k to 200k tokens").
  - why_it_matters: 1 sentence — the concrete developer benefit or workflow change
    (e.g. "Teams can now index monorepos without hitting token limits mid-session").
  - date: ISO date string if visible in the text, else ""

Return JSON:
{{
  "items": [
    {{
      "title": "...",
      "what_changed": "...",
      "why_it_matters": "...",
      "date": "..."
    }}
  ]
}}
If no clear changelog entries are found, return {{"items": []}}"""


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
            max_tokens=600,
            temperature=0,
            system=_SYSTEM,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )
        raw = strip_json_fences(msg.content[0].text)
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
        what_changed = item.get("what_changed", "").strip()
        why_it_matters = item.get("why_it_matters", "").strip()
        summary = f"{what_changed} {why_it_matters}".strip() if why_it_matters else what_changed
        results.append({
            "source": source_name,
            "title": title,
            "link": source_url,
            "summary": summary,
            "published": item.get("date") or today,
        })

    log.info("changelog_agent: %d items from %s", len(results), source_name)
    return results
