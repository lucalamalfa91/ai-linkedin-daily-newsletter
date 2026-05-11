import json
import logging

import anthropic

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a technical editor writing for a senior developer newsletter on AI coding tools.
Given a story about an AI coding tool update, write two sections.

SUMMARY (3-4 sentences):
Explain concretely what was released or changed, how it works, and what problem it solves.
Be specific — name the feature, the mechanism, the scope. Avoid vague claims.
Instead of "improves performance", say what actually changes (e.g. "processes files in parallel
using async subagents instead of sequentially", "adds a dedicated indexing thread").
Include the actual substance: what can users do now that they couldn't before?

CONSIDERATIONS (4-5 sentences, Claude's analytical take):
Cover all of the following:
1. At least one concrete real-world scenario: describe a specific developer workflow or task
   where this change has a visible impact (e.g. "When refactoring a 50-file monorepo, the new
   parallel builds mean each file gets its own subagent — cutting wall time by up to N×").
2. Possible application areas or use cases developers might not have thought of yet.
3. Why this matters now — what gap, trend, or pain point this addresses.
4. Any trade-off, cost, migration cost, or gotcha worth flagging.

Be direct and opinionated like a staff engineer briefing their team. No filler.
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

    user_content = (
        f"Title: {title}\n"
        f"Source: {source}\n"
        f"URL: {url}\n"
        f"Raw excerpt from source: {raw_summary[:600]}"
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=700,
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
