import json
import logging
import re

import anthropic

from config import BANNED_WORDS

log = logging.getLogger(__name__)

_WRITER_SYSTEM = """\
Write a LinkedIn post about an AI story for Luca, a senior software engineer in Switzerland.
Audience: developers, tech managers, recruiters, curious non-experts.

Format (strict):
HOOK: ≤8 words, no question mark — must earn a "see more" click
[blank line]
BODY: 2-3 sentences, one emoji placed naturally, no URL in text
[blank line]
TAKEAWAY: one punchy sentence (use an analogy if possible)
QUESTION: specific to the story, not generic engagement bait
[blank line]
HASHTAGS: 2-3

Voice: punchy short sentences, technical but accessible, natural English. No fake enthusiasm.
No lists, no call-to-action, no structured breakdowns. Must NOT sound AI-generated.
Banned: game-changer, revolutionary, unlock, empower, leverage, synergy, groundbreaking,
paradigm, delve, transformative, unleash, harness, redefine, cutting-edge, state-of-the-art.

Return ONLY valid JSON: {"comment": "<post text with \\n for line breaks>"}
"""

_CRITIC_SYSTEM = """\
You are a strict LinkedIn post quality checker. Return valid JSON only — no markdown fences.

Score a LinkedIn post 0-10: {"score": N, "issues": [...]}

Criteria:
  Hook (2pts): ≤8 words, creates curiosity or contrast, earns "see more"
  Format (2pts): HOOK / blank / BODY / blank / TAKEAWAY + QUESTION / blank / HASHTAGS
  Tone (2pts): natural, not AI-sounding, no URL in text, no call-to-action phrase
  Question (2pts): specific to the story — NOT "What do you think?" or similar
  Banned words (1pt): none of: """ + ", ".join(BANNED_WORDS) + """
  Value (1pt): clear takeaway explaining why the news matters\
"""


def _strip_json_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text)


def write_post(story: dict, original: dict | None, client: anthropic.Anthropic) -> str | None:
    """Generate LinkedIn post text via Claude Sonnet. Returns comment string or None."""
    summary = (original.get("summary") or "")[:300] if original else ""
    source = original.get("source", "") if original else ""

    user = (
        f"Story: {story['title']}\n"
        f"Source: {source}\n"
        f"Summary: {summary}\n\n"
        "Example of a good hook: \"OpenAI just killed the fine-tuning excuse.\"\n"
        "Example of a good question: \"Which part of your stack breaks first when agents start writing agents?\"\n\n"
        "Do NOT include the URL — it is attached as a link card automatically.\n\n"
        'Return: {"comment": "<HOOK\\n\\nBODY\\n\\nTAKEAWAY\\nQUESTION\\n\\nHASHTAGS>"}'
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        temperature=0.7,
        system=[{"type": "text", "text": _WRITER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    raw = _strip_json_fences(msg.content[0].text)
    log.debug("Writing raw: %s", raw)
    try:
        return json.loads(raw).get("comment") or None
    except json.JSONDecodeError:
        log.error("Writing LLM returned invalid JSON: %s", raw)
        return None


def critique_post(comment: str, client: anthropic.Anthropic) -> dict:
    """Score the post via Claude Haiku. Returns {"score": int, "issues": list[str]}."""
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        temperature=0,
        system=_CRITIC_SYSTEM,
        messages=[{"role": "user", "content": f"POST:\n{comment}"}],
    )
    raw = _strip_json_fences(msg.content[0].text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Critic returned invalid JSON: %s — assuming OK", raw)
        return {"score": 10, "issues": []}


def truncate_comment(comment: str) -> str:
    """Hard-cap to 6 non-hashtag lines + hashtag line."""
    lines = comment.split("\n")
    content_lines = [l for l in lines if not l.strip().startswith("#")]
    hashtag_lines = [l for l in lines if l.strip().startswith("#")]
    if len(content_lines) > 6:
        log.warning("Comment exceeded 6 content lines (%d) — truncating", len(content_lines))
        content_lines = content_lines[:6]
    return "\n".join(content_lines + hashtag_lines)
