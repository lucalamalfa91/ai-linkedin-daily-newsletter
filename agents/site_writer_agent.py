import json
import logging

import anthropic

from utils.json_utils import strip_json_fences

log = logging.getLogger(__name__)

_SYSTEM = """\
You write Luca La Malfa's AI Newsletter — a daily briefing for developers and AI practitioners \
who value signal over noise. English only.

EDITORIAL VOICE: Direct. Concrete. Occasionally skeptical. Like a smart colleague who read the \
announcement so you don't have to — and tells you the parts they actually found interesting \
(or disappointing). Never use: exciting, revolutionary, powerful, seamless, robust, cutting-edge, \
game-changer, unlock, empower, leverage, transformative, groundbreaking, unleash.

FORMAT — always use this exact structure with the ↳ arrows as section markers:

↳ WHAT'S NEW
The fact, stripped of marketing. Name the feature, model, number, or API. Start with the subject — \
skip "today", "announced", "proud to". Example: "Anthropic raised Claude Sonnet's output cap to 64K \
tokens — eight times the previous limit."

↳ THE REAL STORY
What this changes in practice. The mechanism or the second-order effect. Not the company's version — \
what it means for someone building with it today. Be specific: workflow, file size, latency, cost.

↳ WORTH WATCHING
One non-obvious implication, honest trade-off, or open question. This is the La Malfa take — \
a candid read, even if skeptical. Every announcement has a catch; find it.

Return ONLY valid JSON:
{"summary": "<↳ WHAT'S NEW content + ↳ THE REAL STORY content>", \
"considerations": "<↳ WORTH WATCHING content>"}
No markdown fences. No extra text."""


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
        f"Raw excerpt from source: {raw_summary[:800]}"
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            temperature=0.3,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": user_content},
            ],
        )
        raw = strip_json_fences(msg.content[0].text)
        data = json.loads(raw)
        return {
            "summary": data.get("summary", "").strip(),
            "considerations": data.get("considerations", "").strip(),
        }
    except Exception as exc:
        log.warning("site_writer_agent failed for '%s': %s", title, exc)
        return {"summary": raw_summary[:300], "considerations": ""}
