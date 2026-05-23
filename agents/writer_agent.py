import json
import logging
import re

import anthropic

from config import BANNED_WORDS

log = logging.getLogger(__name__)

_WRITER_SYSTEM = """\
Write a LinkedIn post for Luca La Malfa, an AI Architect advising enterprises in Switzerland and Europe.
Primary audience: CTOs, Heads of Innovation, CEOs — decision-makers evaluating or scaling AI.

GOAL: make an executive think "this person understands my problem" or "I need to follow this person."
Luca speaks as a practitioner, not a commentator. He works with this technology and has a point of view.

Format (strict):
HOOK: ≤8 words, no question mark — must speak to a business pain, competitive fear, or executive blind spot
[blank line]
BODY: 3 sentences max. One emoji placed naturally, no URL in text.
  — Sentence 1: what is shifting in the market (the business context, not the feature)
  — Sentence 2: the concrete enterprise implication — name a workflow, a cost, a risk, a speed delta
  — Sentence 3: first-person field observation ("We're seeing this in client projects." / "In every architecture review I run...")
[blank line]
TAKEAWAY: one sentence that repositions the reader's mental model — the "La Malfa take"
QUESTION: one question a CTO or Head of Innovation would genuinely wrestle with about their own org
[blank line]
HASHTAGS: 2-3 — always include at least one of: #AIStrategy #EnterpriseAI #AIArchitecture #DigitalTransformation

Hook examples that stop executives mid-scroll:
  "Most AI projects fail before they start."
  "Your competitors are already automating this."
  "The real AI bottleneck isn't the model."
  "Three months ago a CTO asked me this question."
  "Your AI PoC will never reach production. Here's why."

Executive question examples that generate conversations:
  "What's the real blocker between your AI PoC and production?"
  "Who owns the AI roadmap in your org — IT or the business?"
  "Is your governance model ready for agents that manage other agents?"
  "What happens to your team structure when AI handles the first draft of everything?"

Voice: authoritative but not arrogant. Direct. Occasionally provocative. Natural English — must NOT sound AI-generated.
No lists, no call-to-action, no structured breakdowns.
Banned: """ + ", ".join(BANNED_WORDS) + """.

Return ONLY valid JSON: {"comment": "<post text with \\n for line breaks>"}
"""

_CRITIC_SYSTEM = """\
You are a strict LinkedIn post quality checker for an AI Architect targeting C-suite executives.
Return valid JSON only — no markdown fences.

Score a LinkedIn post 0-10: {"score": N, "issues": [...]}

Criteria:
  Hook (2pts): ≤8 words, speaks to a business pain or executive fear — NOT a tech curiosity
  Business angle (2pts): contains a concrete enterprise implication (cost, speed, risk, competitive) — not just a tech fact
  Field credibility (2pts): includes a first-person practitioner signal ("we see", "in client projects", "every architecture review")
  Question (2pts): an executive would genuinely wrestle with it about their own org — NOT "What do you think?" or similar
  Banned words (1pt): none of: """ + ", ".join(BANNED_WORDS) + """
  Tone (1pt): natural, not AI-sounding, no URL in text, no call-to-action phrase\
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
