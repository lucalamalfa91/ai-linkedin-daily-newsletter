import json
import logging
import re

import anthropic

from config import FOCUS_TOPICS, RANKED_TOP_N, SOURCE_CATEGORIES

log = logging.getLogger(__name__)

_SYSTEM = (
    "Score AI news stories for a LinkedIn audience. "
    "Reply ONLY with valid JSON — no markdown fences, no extra text."
)

_RUBRIC_BASE = f"""\
Score each story 0-10. Return JSON: {{"ranked": [{{"rank": 1, "score": 8, "title": "...", "url": "..."}}]}}

SOURCE BONUS (pick the highest that applies):
  +3  LLM Efficiency & Prompt Engineering: {", ".join(SOURCE_CATEGORIES["LLM Efficiency & Prompt Engineering"])}
  +2  Agentic AI & Frameworks: {", ".join(SOURCE_CATEGORIES["Agentic AI & Frameworks"])}
  +1  AI Labs: {", ".join(SOURCE_CATEGORIES["AI Labs"])}
  +1  Practitioners & Researchers: {", ".join(SOURCE_CATEGORIES["Practitioners & Researchers"])}

CONTENT:
  +2  Concrete release (model, product, open-source, benchmark)
  +1  Technical but accessible
  -2  Opinion or commentary with no concrete news
  -3  Pure marketing, no technical content

TOPIC:
  +3  Directly covers a focus topic: __FOCUS_TOPICS__
  +2  LLM efficiency, token optimisation, inference cost, prompt engineering
  +1  Agentic AI, agent frameworks, orchestration
  -3  No meaningful AI angle

TREND & TIMING:
  +2  Appears in trending topics list
  +1  At center of current AI discourse (agents, reasoning, multimodal, cost, AI coding)
  -1  Old news already widely covered

LINKEDIN VALUE:
  +2  Surprising, specific, or counterintuitive
  +1  Positions author as knowledgeable and ahead
  -2  Looks like reposting a press release

Cap 10, floor 0. Return top {RANKED_TOP_N} only. Copy URLs exactly — never invent one.\
"""


def _detect_trending_topics(items: list[dict]) -> str:
    _stop = {
        "the", "and", "for", "with", "this", "that", "from", "have", "been",
        "will", "are", "its", "how", "new", "more", "what", "can", "about",
        "your", "our", "their", "using", "used", "based", "which", "model",
        "models", "data", "blog", "post", "update", "deep", "neural", "large",
        "language", "learn", "learning", "research", "paper", "work", "make",
        "open", "like", "also", "they", "when", "into", "just", "some",
    }
    keyword_sources: dict[str, set] = {}
    for item in items:
        text = (item["title"] + " " + item.get("summary", "")).lower()
        seen: set[str] = set()
        for w in re.findall(r"\b[a-z]{4,15}\b", text):
            if w in _stop or w in seen:
                continue
            seen.add(w)
            keyword_sources.setdefault(w, set()).add(item["source"])
    trending = sorted(
        [w for w, srcs in keyword_sources.items() if len(srcs) >= 3],
        key=lambda w: -len(keyword_sources[w]),
    )
    return ", ".join(trending[:12]) if trending else "none detected"


def rank_stories(
    items: list[dict],
    client: anthropic.Anthropic,
    performance_bonus: str = "",
    last_published_source: str = "",
    focus_topics: str = "",
) -> list[dict]:
    """Call Claude Haiku to score and rank stories. Returns ranked list or [] on failure."""
    if not items:
        return []

    active_topics = focus_topics or FOCUS_TOPICS
    trending = _detect_trending_topics(items)
    feed_lines = "\n".join(
        f"[{i + 1}] ({it['source']}) {it['title']} — {it['link']} — {it['summary'][:200]}"
        for i, it in enumerate(items[:40])
    )

    dynamic_parts = [
        f"AI news from the last 7 days:\n{feed_lines}",
        f"Trending topics across multiple sources: {trending}",
    ]
    if performance_bonus:
        dynamic_parts.append(
            "ADAPTIVE RANKING (from past post performance):\n" + performance_bonus
        )
    if last_published_source:
        dynamic_parts.append(
            f"SOURCE DIVERSITY: '{last_published_source}' published last week — apply -1 to avoid repetition."
        )

    rubric = _RUBRIC_BASE.replace("__FOCUS_TOPICS__", active_topics[:120])
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        temperature=0,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": rubric, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "\n\n".join(dynamic_parts)},
                ],
            },
            {"role": "assistant", "content": "{"},
        ],
    )
    raw = "{" + msg.content[0].text.strip()
    log.debug("Ranking raw: %s", raw)
    try:
        return json.loads(raw).get("ranked", [])
    except json.JSONDecodeError:
        log.error("Ranking LLM returned invalid JSON: %s", raw)
        return []
