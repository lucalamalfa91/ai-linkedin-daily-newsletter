"""Generates self-made feature spotlight articles from Claude Code documentation pages."""

import json
import logging
from datetime import datetime, timezone

import anthropic

log = logging.getLogger(__name__)

_SYSTEM = """\
You write feature spotlight articles for senior software developers.
Given a Claude Code documentation page, write a self-contained article that a developer
would genuinely find worth reading — not a paraphrase of the docs.

Your article must cover:
- What the feature does and how it actually works (the mechanism, not just the effect)
- The most interesting or non-obvious aspect that the docs bury or understate
- At least one concrete developer scenario: a specific task or workflow where this feature
  changes the outcome (e.g. "When running a 200-file migration, hooks let you validate
  each write before it lands — catching schema drift before it accumulates")
- Practical implications: when to use it, what it replaces, any gotchas or limits

Tone: like a knowledgeable colleague who just spent an hour with the docs and is
sharing the useful parts — direct, specific, no marketing language.
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
  "summary": "3-4 sentences: what it is, how it works technically, and one concrete developer scenario",
  "hook": "1 sentence: the most interesting or non-obvious thing about this feature — something a developer would forward to their team"
}}

If the page has insufficient content, return {{"title": "", "summary": "", "hook": ""}}"""


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
            max_tokens=500,
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
        "_is_feature_spotlight": True,
    }
