#!/usr/bin/env python3
"""LinkedIn AI News Post — multi-agent pipeline.

Flow: analytics update → fetch RSS feeds → (optional) filter by topic
      → rank stories → pick best → write post → publish LinkedIn → notify Telegram.

The TOPIC env var (or --topic flag) can be used to restrict which stories are
considered.  Pass "claude code" (or any substring, case-insensitive) to publish
only Claude Code / Anthropic news from the RSS feeds.  Leave empty for the full
newsletter pool.

NOTE: This pipeline is independent from site_pipeline.py.  site_pipeline.py writes
news.json / index.html for the website.  This script publishes to LinkedIn from
the live RSS feeds — so every post is based on a real, dated article.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import anthropic

from agents.analytics_agent import compute_performance_bonuses, update_analytics
from agents.feed_agent import fetch_feeds
from agents.notifier_agent import request_approval, send as notify
from agents.publisher_agent import publish
from agents.ranking_agent import rank_stories
from agents.writer_agent import critique_post, truncate_comment, write_post
from config import FOCUS_TOPICS, MIN_SCORE, RSS_FEEDS
from utils.history import commit_history_to_git, extract_hashtags, extract_topics, load_history, save_history
from utils.og_meta import fetch_og_meta
from utils.url_utils import is_valid_url, normalize_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# Sources considered "Claude Code" news — from RSS_FEEDS keys
_CLAUDE_CODE_SOURCES = {"Anthropic", "OpenAI", "Google DeepMind", "Google AI Blog"}
_CLAUDE_CODE_KEYWORDS = {"claude", "anthropic", "claude code"}


def _load_env() -> None:
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_file):
        return
    log.info("Loading .env file")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.removeprefix("export ").strip()
            key, _, val = line.partition("=")
            os.environ[key.strip()] = val.strip('"').strip("'")


def _require_env(*keys: str) -> None:
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        log.error("Missing environment variables: %s", ", ".join(missing))
        sys.exit(1)


def _filter_claude_code(items: list[dict]) -> list[dict]:
    """Keep only items from Anthropic sources or mentioning Claude / Anthropic in title/summary."""
    filtered = []
    for item in items:
        source = item.get("source", "")
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        if source in _CLAUDE_CODE_SOURCES or any(kw in text for kw in _CLAUDE_CODE_KEYWORDS):
            filtered.append(item)
    log.info("Claude Code filter: %d → %d items", len(items), len(filtered))
    return filtered


def _pick_linkedin_story(
    ranked: list[dict],
    items: list[dict],
    client: anthropic.Anthropic,
    performance_bonus: str,
    last_published_source: str,
    focus_topics: str,
) -> dict | None:
    """Ask Claude Haiku to pick the best story from the ranked top-N."""
    candidates = [r for r in ranked if r.get("score", 0) >= MIN_SCORE][:5]
    if not candidates:
        return None
    if len(candidates) == 1:
        return _enrich_from_items(candidates[0], items)

    lines = [
        f"[{s.get('rank', '?')}] score={s.get('score', 0)} title={s.get('title', '')} url={s.get('url', '')}"
        for s in candidates
    ]
    bonus_section = f"\nHISTORICAL PERFORMANCE:\n{performance_bonus}" if performance_bonus else ""
    diversity_section = (
        f"\nSOURCE DIVERSITY: '{last_published_source}' published last time — prefer a different source."
        if last_published_source else ""
    )
    prompt = (
        f"Pick the single best story for a LinkedIn post targeting AI/developer professionals.\n\n"
        f"FOCUS: {focus_topics[:200]}\n{bonus_section}{diversity_section}\n\n"
        f"STORIES:\n" + "\n".join(lines) + "\n\nReturn ONLY valid JSON: {\"rank\": <number>}"
    )
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            temperature=0,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + msg.content[0].text.strip()
        chosen_rank = json.loads(raw).get("rank")
        for s in candidates:
            if s.get("rank") == chosen_rank:
                log.info("Claude selected rank=%s: %s", chosen_rank, s.get("title"))
                return _enrich_from_items(s, items)
    except Exception as exc:
        log.warning("Story selection LLM failed (%s) — falling back to top ranked", exc)

    return _enrich_from_items(max(candidates, key=lambda s: s.get("score", 0)), items)


def _enrich_from_items(ranked_story: dict, items: list[dict]) -> dict:
    """Attach the original RSS item fields (source, summary) to a ranked story dict."""
    url = normalize_url(ranked_story.get("url", ""))
    original = (
        next((it for it in items if normalize_url(it["link"]) == url), None)
        or next((it for it in items if it["title"] == ranked_story.get("title")), None)
    )
    result = dict(ranked_story)
    if original:
        result.setdefault("source", original.get("source", ""))
        result.setdefault("summary", original.get("summary", ""))
    return result


def _select_story(
    items: list[dict],
    client: anthropic.Anthropic,
    focus_topics: str,
    performance_bonus: str,
    last_published_source: str,
    published_urls: set[str],
) -> tuple[str | None, dict | None]:
    """Rank RSS items → pick best → validate → write → critique. Returns (comment, story)."""
    # Exclude already-published URLs
    fresh = [it for it in items if normalize_url(it["link"]) not in published_urls]
    log.info("Items after dedup filter: %d (from %d total)", len(fresh), len(items))
    if not fresh:
        return None, None

    ranked = rank_stories(
        fresh,
        client,
        performance_bonus=performance_bonus,
        last_published_source=last_published_source,
        focus_topics=focus_topics,
        top_n=len(fresh),
    )
    if not ranked:
        log.warning("Ranking returned no results")
        return None, None

    story = _pick_linkedin_story(ranked, fresh, client, performance_bonus, last_published_source, focus_topics)
    if not story:
        log.info("No story met minimum score threshold")
        return None, None

    url = normalize_url(story.get("url", ""))
    if not is_valid_url(url):
        log.warning("Selected story has invalid URL '%s' — aborting", url)
        return None, None

    story["url"] = url

    og = fetch_og_meta(url)
    if not og.get("image"):
        log.info("No thumbnail for '%s' — skipping", story.get("title"))
        return None, None

    story["og"] = og

    original = {
        "source": story.get("source", ""),
        "summary": story.get("summary", ""),
    }

    log.info("Writing post for: %s (score=%s)", story.get("title"), story.get("score"))
    comment = write_post(story, original, client)
    if not comment:
        log.warning("write_post failed")
        return None, None

    for attempt in range(2):
        critique = critique_post(comment, client)
        c_score = critique.get("score", 10)
        log.info("Critic attempt=%d score=%d issues=%s", attempt + 1, c_score, critique.get("issues", []))
        if c_score >= 7:
            break
        if attempt == 0:
            log.warning("Critic score=%d — retrying post generation", c_score)
            retry = write_post(story, original, client)
            if retry:
                comment = retry

    comment = truncate_comment(comment)
    return comment, story


def main() -> None:
    _load_env()
    _require_env(
        "LINKEDIN_ACCESS_TOKEN",
        "LINKEDIN_PERSON_ID",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ANTHROPIC_API_KEY",
    )

    parser = argparse.ArgumentParser(description="LinkedIn AI News Post")
    parser.add_argument("--topic", type=str, default=None, help="Custom focus topic override")
    parser.add_argument("--no-confirm", action="store_true", help="Skip Telegram approval")
    parser.add_argument(
        "--claude-code-only",
        action="store_true",
        help="Only consider Claude Code / Anthropic news from RSS feeds",
    )
    args = parser.parse_args()

    raw_topic = args.topic or os.environ.get("TOPIC") or ""
    focus = raw_topic or FOCUS_TOPICS
    skip_confirm = args.no_confirm or os.environ.get("SKIP_CONFIRM") == "1"
    # Auto-detect claude-code-only mode from topic string
    claude_code_only = args.claude_code_only or (
        "claude" in raw_topic.lower() if raw_topic else False
    )

    if focus != FOCUS_TOPICS:
        log.info("Using custom topic: %s", focus)
    if claude_code_only:
        log.info("Claude Code-only mode: filtering RSS to Anthropic / Claude-related items")

    tg_token  = os.environ["TELEGRAM_BOT_TOKEN"]
    tg_chat   = os.environ["TELEGRAM_CHAT_ID"]
    token     = os.environ["LINKEDIN_ACCESS_TOKEN"]
    person_id = os.environ["LINKEDIN_PERSON_ID"]
    client    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Analytics update (best-effort)
    history = load_history()
    history = update_analytics(history, token)
    save_history(history)

    # Adaptive ranking inputs
    performance_bonus = compute_performance_bonuses(history)
    if performance_bonus:
        log.info("Adaptive ranking bonuses:\n%s", performance_bonus)

    last_published_source = ""
    published_urls: set[str] = set()
    if history:
        records = list(history.values())
        latest = max(records, key=lambda r: r.get("published_at", ""), default=None)
        if latest:
            last_published_source = latest.get("source", "")
            log.info("Last published source: %s", last_published_source)
        published_urls = {normalize_url(r["article_url"]) for r in records if r.get("article_url")}
        log.info("Dedup filter: %d already-published URLs", len(published_urls))

    try:
        # Fetch live RSS feeds — real dated articles only
        items = fetch_feeds(days=7)

        if not items:
            notify(
                "<b>AI LinkedIn Post</b>: no RSS items found in the last 7 days.",
                tg_token, tg_chat,
            )
            log.info("No RSS items — skipping LinkedIn post.")
            return

        # Optional Claude Code filter
        if claude_code_only:
            items = _filter_claude_code(items)
            if not items:
                notify(
                    "<b>AI LinkedIn Post</b>: no Claude Code / Anthropic news in the last 7 days.",
                    tg_token, tg_chat,
                )
                log.info("No Claude Code items after filter — skipping.")
                return

        comment, story = _select_story(
            items, client, focus, performance_bonus, last_published_source, published_urls
        )

        if not comment:
            notify(
                "<b>AI LinkedIn Post</b>: no qualifying story found in today's RSS feed. "
                "All recent items may already be published or lack a thumbnail.",
                tg_token, tg_chat,
            )
            log.info("No qualifying story — skipping LinkedIn post.")
            return

        log.info("Publishing: %s (score %s)", story["title"], story["score"])

        if not skip_confirm:
            preview = (
                f"<b>\U0001f4dd Post da pubblicare su LinkedIn</b>\n\n"
                f"<b>{story['title']}</b>\n"
                f"\u2b50 Score: {story['score']}/10\n"
                f"\U0001f517 {story['url']}\n\n"
                f"<i>{comment}</i>"
            )
            approved = request_approval(preview, tg_token, tg_chat)
            if not approved:
                notify("\u23ed Post annullato o timeout — nessuna pubblicazione.", tg_token, tg_chat)
                log.info("Post not approved — skipping LinkedIn publication")
                return

        post_id = publish(
            comment,
            story["url"],
            story["title"],
            person_id,
            token,
            og=story.get("og"),
        )

        history[post_id] = {
            "post_id":       post_id,
            "published_at":  datetime.now(timezone.utc).isoformat(),
            "article_url":   story["url"],
            "article_title": story["title"],
            "source":        story.get("source", ""),
            "score":         story.get("score", 0),
            "comment_text":  comment,
            "topics":        extract_topics(story["title"], comment),
            "hashtags":      extract_hashtags(comment),
            "analytics":     None,
        }
        save_history(history)
        commit_history_to_git()

        notify(
            "\u2705 <b>LinkedIn post published!</b>\n\n"
            f"\U0001f4cc <b>{story['title']}</b>\n"
            f"\U0001f517 {story['url']}\n"
            f"\u2b50 Score: {story['score']}/10 (rank #{story.get('rank', '?')})\n\n"
            f"\U0001f4ac <i>{comment}</i>\n\n"
            f"\U0001f194 Post ID: {post_id}",
            tg_token, tg_chat,
        )
        log.info("Pipeline completed successfully")

    except Exception as exc:
        log.exception("Pipeline failed")
        notify(f"\u274c <b>AI LinkedIn Post FAILED</b>\n\n{exc}", tg_token, tg_chat)
        sys.exit(1)


if __name__ == "__main__":
    main()
