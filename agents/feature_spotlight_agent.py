"""Generates self-made feature spotlight articles from Claude Code documentation pages."""

import json
import logging
from datetime import datetime, timezone

import anthropic

from utils.json_utils import strip_json_fences

log = logging.getLogger(__name__)

_SYSTEM = """\
You write feature spotlight articles for senior software developers.
Given a Claude Code documentation page, write a self-contained article that a developer
would genuinely find worth reading and forward to their team.

Your article must not paraphrase the docs. Instead, it must answer:
1. What does this feature actually do at the mechanism level — not the marketing summary?
   (e.g. "hooks intercept every tool call before execution, giving you a synchronous
   checkpoint to validate, log, or abort — without patching Claude's internals")
2. What is the single most interesting or non-obvious thing about this feature that the
   docs bury, understate, or leave for the reader to figure out?
3. One concrete developer scenario: a specific task, codebase, or pipeline where this
   feature changes the outcome. Be specific — name file counts, error types, latency,
   the stage in the workflow. Generic "it helps with X" is not acceptable.
4. What does this replace or make obsolete? What's the honest gotcha or limit?

Hook: The opening hook should be a single punchy sentence that a developer would
immediately want to share — something that reframes the feature in a way the docs don't.
Example: "Claude Code hooks are basically middleware for your AI pair programmer —
and they run synchronously, which means you can actually block bad writes."

Tone: knowledgeable colleague who just spent an hour with the docs and is cutting
through the noise — direct, specific, occasionally surprising.
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
  "title": "compelling title max 12 words — starts with the feature name, not 'Claude Code'",
  "hook": "1 punchy sentence: the most interesting or non-obvious thing — something a developer would forward to their team",
  "summary": "3-4 sentences: what it does (mechanism), the non-obvious insight, one concrete developer scenario with specifics, honest trade-off or limit",
  "cta": "1 sentence: what should the reader do or explore next — be specific (e.g. 'Try adding a hook that validates JSON schema before any file write')"
}}

If the page has insufficient content to write something genuinely insightful, return
{{"title": "", "hook": "", "summary": "", "cta": ""}}"""


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
            max_tokens=600,
            temperature=0.4,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": prompt},
            ],
        )
        raw = strip_json_fences(msg.content[0].text)
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
    cta = data.get("cta", "").strip()
    parts = [p for p in [hook, summary, cta] if p]
    full_summary = " ".join(parts)

    log.info("feature_spotlight: generated article '%s'", title)
    return {
        "source": "Claude Code Docs",
        "title": title,
        "link": page_url,
        "summary": full_summary,
        "published": datetime.now(timezone.utc).isoformat(),
        "_is_feature_spotlight": True,
    }
