#!/usr/bin/env python3
"""LinkedIn AI News Post — multi-agent pipeline.

Flow: analytics update → fetch RSS → rank stories → write post → publish LinkedIn → notify Telegram.
"""

import argparse
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
from config import FOCUS_TOPICS, MIN_SCORE
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


def _select_story(
    items: list[dict],
    client: anthropic.Anthropic,
    focus_topics: str,
    performance_bonus: str,
    last_published_source: str,
) -> tuple[str | None, dict | None]:
    """Rank → validate → write → critique. Returns (comment, story) or (None, None)."""
    ranked = rank_stories(items, client, performance_bonus, last_published_source)
    if not ranked:
        return None, None

    for candidate in ranked:
        score = candidate.get("score", 0)
        url = normalize_url(candidate.get("url", ""))
        rank = candidate.get("rank", "?")

        log.info("Candidate rank=%s score=%d url_valid=%s title=%s", rank, score, is_valid_url(url), candidate.get("title", ""))

        if score < MIN_SCORE:
            log.info("  -> skipped (score %d < threshold %d)", score, MIN_SCORE)
            continue
        if not is_valid_url(url):
            log.warning("  -> skipped (invalid URL '%s')", url)
            continue

        candidate["url"] = url
        original = next((it for it in items if it["link"] == url), None)

        og = fetch_og_meta(url)
        if not og.get("image"):
            log.info("  -> skipped (no thumbnail available)")
            continue
        candidate["og"] = og

        log.info("Writing post for rank=%s score=%d", rank, score)
        comment = write_post(candidate, original, client)
        if not comment:
            log.warning("  -> write_post failed, trying next candidate")
            continue

        for attempt in range(2):
            critique = critique_post(comment, client)
            c_score = critique.get("score", 10)
            log.info("Critic attempt=%d score=%d issues=%s", attempt + 1, c_score, critique.get("issues", []))
            if c_score >= 7:
                break
            if attempt == 0:
                log.warning("Critic score=%d — retrying post generation", c_score)
                retry = write_post(candidate, original, client)
                if retry:
                    comment = retry

        comment = truncate_comment(comment)
        log.info("Selected candidate rank=%s score=%d", rank, score)
        return comment, candidate

    log.info("No candidate passed validation (threshold=%d)", MIN_SCORE)
    return None, None


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
    parser.add_argument("--topic", type=str, default=None, help="Custom focus topic (overrides FOCUS_TOPICS)")
    parser.add_argument("--no-confirm", action="store_true", help="Skip Telegram approval step and publish immediately")
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
        items = fetch_feeds()
        comment, story = _select_story(items, client, focus, performance_bonus, last_published_source)

        if not comment:
            notify(
                f"<b>AI LinkedIn Post</b>: no qualifying news (threshold={MIN_SCORE}/10 across 7 days). "
                "Skipping — consider checking feed sources.",
                tg_token, tg_chat,
            )
            log.info("No qualifying news in 7 days — skipping LinkedIn post.")
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
