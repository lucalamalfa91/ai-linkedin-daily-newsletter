"""Generates self-made feature spotlight articles from Claude Code documentation pages."""

import json
import logging
from datetime import datetime, timezone

import anthropic

log = logging.getLogger(__name__)

_SYSTEM = """\
You write feature spotlight articles for senior software developers.
Given a Claude Code documentation page, produce a self-contained article that:
- Explains what the feature does concisely (not a copy of the docs)
- Highlights the most interesting or non-obvious aspects
- Gives a concrete example use case developers will recognise
- Points out limitations or gotchas worth knowing

Tone: like a knowledgeable colleague sharing something useful, not a press release.
Reply ONLY with valid JSON — no markdown fences, no extra text."""

_PROMPT = """\
Feature: {feature_name}
Docs URL: {url}
Documentation text (truncated):
---
{text}
---

Write a feature spotlight article. Return JSON:
{{
  "title": "compelling title max 12 words, starts with 'Claude Code'",
  "summary": "2-3 sentences: what it is and the key insight developers should know",
  "hook": "1 sentence: the most interesting or surprising thing about this feature"
}}

If the page has insufficient content to write about, return {{"title": "", "summary": "", "hook": ""}}"""


def generate_feature_spotlight(
    feature_name: str,
    page_url: str,
    page_text: str,
    client: anthropic.Anthropic,
) -> dict | None:
    """Generate a self-made feature article from a Claude Code docs page.

    Returns a feed-agent-compatible dict or None if the page lacks content.
    """
    if not page_text.strip():
        log.warning("feature_spotlight: empty page for %s", feature_name)
        return None

    prompt = _PROMPT.format(
        feature_name=feature_name,
        url=page_url,
        text=page_text[:6000],
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            temperature=0.4,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + msg.content[0].text.strip()
        data = json.loads(raw)
    except Exception as exc:
        log.warning("feature_spotlight: LLM failed for %s: %s", feature_name, exc)
        return None

    title = data.get("title", "").strip()
    summary = data.get("summary", "").strip()
    if not title or not summary:
        log.info("feature_spotlight: insufficient content for %s", feature_name)
        return None

    hook = data.get("hook", "").strip()
    full_summary = f"{hook} {summary}".strip() if hook else summary

    log.info("feature_spotlight: generated article '%s'", title)
    return {
        "source": "Claude Code Docs",
        "title": title,
        "link": page_url,
        "summary": full_summary,
        "published": datetime.now(timezone.utc).isoformat(),
        "_is_feature_spotlight": True,  # used by ranking to apply Claude Code boost
    }
