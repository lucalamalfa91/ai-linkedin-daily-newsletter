import json
import logging

import anthropic

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a technical analyst writing for senior software engineers.
Given an AI coding tool news story, produce exactly two things:

SUMMARY: 2-3 factual sentences covering what was announced, released, or changed
and its scope. Facts only — no adjectives like "powerful", "revolutionary", or "exciting".

CONSIDERATIONS: 2-4 sentences a senior developer would send to their team on Slack.
Cover the practical angle: what to test, trade-offs, adoption timing, cost/complexity
implications, or what could break. Be specific and opinionated, not vague.

Return ONLY valid JSON: {"summary": "...", "considerations": "..."}
No markdown fences, no extra text."""


def write_site_entry(
    candidate: dict,
    original: dict | None,
    client: anthropic.Anthropic,
) -> dict:
    """Generate summary and considerations for a story. Returns {"summary": ..., "considerations": ...}."""
    title = candidate.get("title", "")
    url = candidate.get("url", "")
    source = original.get("source", "") if original else candidate.get("source", "")
    raw_summary = original.get("summary", "") if original else ""

    user_content = f"Title: {title}\nSource: {source}\nURL: {url}\nRaw excerpt: {raw_summary[:500]}"

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            temperature=0.3,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + msg.content[0].text.strip()
        data = json.loads(raw)
        return {
            "summary": data.get("summary", "").strip(),
            "considerations": data.get("considerations", "").strip(),
        }
    except Exception as exc:
        log.warning("site_writer_agent failed for '%s': %s", title, exc)
        return {"summary": raw_summary[:300], "considerations": ""}
