#!/usr/bin/env python3
"""LinkedIn AI News Post — multi-agent pipeline.

Flow: analytics update → load site/news.json → pick best story → write post
      → publish LinkedIn → notify Telegram.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agents.analytics_agent import compute_performance_bonuses, update_analytics
from agents.notifier_agent import request_approval, send as notify
from agents.publisher_agent import publish
from agents.writer_agent import critique_post, truncate_comment, write_post
from config import FOCUS_TOPICS, MIN_SCORE, NEWS_JSON_PATH
from utils.history import commit_history_to_git, extract_hashtags, extract_topics, load_history, save_history
from utils.og_meta import fetch_og_meta
from utils.url_utils import is_valid_url, normalize_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


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


def _load_news_json() -> list[dict]:
    """Load pre-ranked stories from site/news.json (written daily by site_pipeline.py)."""
    path = Path(NEWS_JSON_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"site/news.json not found at {path}. "
            "Run site_pipeline.py first, or trigger the update_site GitHub Actions workflow."
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    stories = data.get("stories", [])
    log.info("Loaded %d stories from news.json (generated %s)", len(stories), data.get("generated_at", "?"))
    return stories


def _pick_linkedin_story(
    stories: list[dict],
    client: anthropic.Anthropic,
    performance_bonus: str,
    last_published_source: str,
) -> dict | None:
    """Ask Claude Haiku to pick the single best story from the 3 for LinkedIn."""
    if not stories:
        return None
    if len(stories) == 1:
        return stories[0]

    lines = []
    for s in stories:
        lines.append(
            f"[{s.get('rank', '?')}] score={s.get('score', 0)} source={s.get('source', '')} "
            f"title={s.get('title', '')} url={s.get('url', '')}"
        )
    feed_block = "\n".join(lines)

    bonus_section = ""
    if performance_bonus:
        bonus_section = f"\nHISTORICAL PERFORMANCE:\n{performance_bonus}"
    diversity_section = ""
    if last_published_source:
        diversity_section = f"\nSOURCE DIVERSITY: '{last_published_source}' published last time — prefer a different source."

    prompt = (
        f"Pick the single best story for a LinkedIn post targeting AI/developer professionals.\n\n"
        f"FOCUS: {FOCUS_TOPICS[:200]}\n{bonus_section}{diversity_section}\n\n"
        f"STORIES:\n{feed_block}\n\n"
        "Return ONLY valid JSON: {\"rank\": <number>}"
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
        for s in stories:
            if s.get("rank") == chosen_rank:
                log.info("Claude selected rank=%s: %s", chosen_rank, s.get("title"))
                return s
    except Exception as exc:
        log.warning("Story selection LLM failed (%s) — falling back to rank #1", exc)

    # Fallback: highest-scored story
    return max(stories, key=lambda s: s.get("score", 0))


def _select_story(
    stories: list[dict],
    client: anthropic.Anthropic,
    focus_topics: str,
    performance_bonus: str,
    last_published_source: str,
) -> tuple[str | None, dict | None]:
    """Pick story from news.json → validate → write → critique. Returns (comment, story) or (None, None)."""
    story = _pick_linkedin_story(stories, client, performance_bonus, last_published_source)
    if not story:
        return None, None

    url = normalize_url(story.get("url", ""))
    if not is_valid_url(url):
        log.warning("Selected story has invalid URL '%s' — aborting", url)
        return None, None

    story["url"] = url

    # Use cached og_image from news.json; fetch fresh only if missing
    og: dict = {}
    if story.get("og_image"):
        og = {"image": story["og_image"]}
    else:
        og = fetch_og_meta(url)

    if not og.get("image"):
        log.info("No thumbnail for '%s' — skipping", story.get("title"))
        return None, None

    story["og"] = og

    # Build a compatible "original" dict for write_post
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
    parser.add_argument("--no-confirm", action="store_true", help="Skip Telegram approval and publish immediately")
    args = parser.parse_args()
    focus = args.topic or os.environ.get("TOPIC") or FOCUS_TOPICS
    skip_confirm = args.no_confirm or os.environ.get("SKIP_CONFIRM") == "1"
    if focus != FOCUS_TOPICS:
        log.info("Using custom topic: %s", focus)

    tg_token  = os.environ["TELEGRAM_BOT_TOKEN"]
    tg_chat   = os.environ["TELEGRAM_CHAT_ID"]
    token     = os.environ["LINKEDIN_ACCESS_TOKEN"]
    person_id = os.environ["LINKEDIN_PERSON_ID"]
    client    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Analytics update (best-effort, before main pipeline)
    history = load_history()
    history = update_analytics(history, token)
    save_history(history)

    # Adaptive ranking inputs
    performance_bonus = compute_performance_bonuses(history)
    if performance_bonus:
        log.info("Adaptive ranking bonuses:\n%s", performance_bonus)

    last_published_source = ""
    if history:
        latest = max(history.values(), key=lambda r: r.get("published_at", ""), default=None)
        if latest:
            last_published_source = latest.get("source", "")
            log.info("Last published source: %s", last_published_source)

    try:
        stories = _load_news_json()
        comment, story = _select_story(stories, client, focus, performance_bonus, last_published_source)

        if not comment:
            notify(
                "<b>AI LinkedIn Post</b>: no qualifying story found in today's digest. "
                "Check site/news.json or re-run site_pipeline.py.",
                tg_token, tg_chat,
            )
            log.info("No qualifying story — skipping LinkedIn post.")
            return

        log.info("Publishing: %s (score %s)", story["title"], story["score"])

        if not skip_confirm:
            preview = (
                f"<b>📝 Post da pubblicare su LinkedIn</b>\n\n"
                f"<b>{story['title']}</b>\n"
                f"⭐ Score: {story['score']}/10\n"
                f"🔗 {story['url']}\n\n"
                f"<i>{comment}</i>"
            )
            approved = request_approval(preview, tg_token, tg_chat)
            if not approved:
                notify("⏭ Post annullato o timeout — nessuna pubblicazione.", tg_token, tg_chat)
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
            "✅ <b>LinkedIn post published!</b>\n\n"
            f"📌 <b>{story['title']}</b>\n"
            f"🔗 {story['url']}\n"
            f"⭐ Score: {story['score']}/10 (rank #{story.get('rank', '?')})\n\n"
            f"💬 <i>{comment}</i>\n\n"
            f"🆔 Post ID: {post_id}",
            tg_token, tg_chat,
        )
        log.info("Pipeline completed successfully")

    except Exception as exc:
        log.exception("Pipeline failed")
        notify(f"❌ <b>AI LinkedIn Post FAILED</b>\n\n{exc}", tg_token, tg_chat)
        sys.exit(1)


if __name__ == "__main__":
    main()
