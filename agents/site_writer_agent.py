import json
import logging

import anthropic

from utils.json_utils import strip_json_fences

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a technical editor for a daily digest read by senior software engineers and AI practitioners.
Your job: make each entry genuinely worth 2 minutes of a developer's time.

SUMMARY (3-4 sentences):
State concretely what changed or was released. Name the specific feature, API, parameter, or fix.
Include the mechanism — how it works under the hood, not just what it does.
Quantify when possible: context-window size, latency delta, token budget, number of tools, file limits.
End with what users can do now that they couldn't before — this is the most important sentence.
Avoid "improves", "enhances", "enables" without specifics.

CONSIDERATIONS (4-5 sentences — Claude's candid analytical take):
1. One concrete developer scenario: a real task or workflow where this change has a measurable impact.
   Be specific: name the tool, the repo size, the latency, the error type, the pipeline step.
   Example: "When iterating over a 300-file codebase with hooks enabled, you can validate every
   write before it commits — catching schema drift that silent sub-agents would otherwise miss."
2. One non-obvious implication or second-order effect developers might not have considered.
3. Why this matters NOW — what trend, bottleneck, or user complaint this directly addresses.
4. One honest trade-off, migration cost, or gotcha worth flagging — even if minor.

Tone: a staff engineer's Slack message to their team after spending an hour with this — direct,
specific, occasionally opinionated, zero marketing language.
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
