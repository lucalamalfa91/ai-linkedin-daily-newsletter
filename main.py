#!/usr/bin/env python3
"""LinkedIn AI News Post — multi-agent pipeline.

Flow: analytics update → load newsletter (news.json) → filter out spotlights
      → pick best story → write post → publish LinkedIn → notify Telegram.

Source of truth: site/news.json generated daily by site_pipeline.py.
Only real changelog/news items are considered (is_feature_spotlight=False).
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
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
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


def _load_newsletter_stories(published_urls: set[str]) -> list[dict]:
    """Load stories from news.json, filter out spotlights and already-published URLs."""
    path = Path(NEWS_JSON_PATH)
    if not path.exists():
        log.error("news.json not found at %s — run site_pipeline.py first", path)
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    stories = data.get("stories", [])
    log.info("news.json loaded: %d stories (generated %s)", len(stories), data.get("generated_at", "?"))

    # Drop feature spotlights (generated from docs, not real news)
    real_news = [s for s in stories if not s.get("is_feature_spotlight", False)]
    log.info("After spotlight filter: %d real news stories", len(real_news))

    # Drop already-published URLs
    fresh = [s for s in real_news if normalize_url(s.get("url", "")) not in published_urls]
    log.info("After dedup filter: %d fresh stories", len(fresh))

    return fresh


def _pick_best_story(
    stories: list[dict],
    client: anthropic.Anthropic,
    focus_topics: str,
    performance_bonus: str,
    last_published_source: str,
) -> dict | None:
    """Among the newsletter stories, pick the best one for LinkedIn.

    Stories are already ranked/scored by site_pipeline.py (rank 1 = best).
    We ask Claude Haiku for a final pick among the top candidates.
    """
    candidates = [s for s in stories if s.get("score", 0) >= MIN_SCORE]
    if not candidates:
        # Fallback: use all stories sorted by rank
        candidates = sorted(stories, key=lambda s: s.get("rank", 99))
    candidates = candidates[:5]

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    lines = [
        f"[{s.get('rank', '?')}] score={s.get('score', 0)} source={s.get('source', '')} "
        f"title={s.get('title', '')} url={s.get('url', '')}"
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
        f"STORIES:\n" + "\n".join(lines)
        + "\n\nReturn ONLY valid JSON: {\"rank\": <number>}"
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
                return s
    except Exception as exc:
        log.warning("Story selection LLM failed (%s) — using rank #1", exc)

    return min(candidates, key=lambda s: s.get("rank", 99))


def _build_og(story: dict) -> dict:
    """Return OG dict. Uses og_image from news.json if present, otherwise fetches live."""
    cached = story.get("og_image")
    if cached:
        return {"image": cached}
    log.info("No cached og_image for '%s' — fetching live", story.get("title"))
    return fetch_og_meta(story.get("url", ""))


def _build_post(story: dict, client: anthropic.Anthropic) -> str | None:
    """Write post + critique loop. Returns final comment or None on failure."""
    original = {
        "source": story.get("source", ""),
        "summary": story.get("summary", ""),
    }
    comment = write_post(story, original, client)
    if not comment:
        log.warning("write_post failed")
        return None

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

    return truncate_comment(comment)


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

    # Analytics update (best-effort)
    history = load_history()
    history = update_analytics(history, token)
    save_history(history)

    # Adaptive ranking inputs from past posts
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
        # Load today's newsletter stories (real news only, no spotlights)
        stories = _load_newsletter_stories(published_urls)

        if not stories:
            notify(
                "<b>AI LinkedIn Post</b>: nessuna storia disponibile in news.json — "
                "tutte già pubblicate o solo spotlight. Esegui site_pipeline.py.",
                tg_token, tg_chat,
            )
            log.info("No fresh newsletter stories — skipping LinkedIn post.")
            return

        # Pick the best story among the newsletter
        story = _pick_best_story(stories, client, focus, performance_bonus, last_published_source)
        if not story:
            notify(
                "<b>AI LinkedIn Post</b>: nessuna storia supera il punteggio minimo.",
                tg_token, tg_chat,
            )
            log.info("No story met minimum score — skipping.")
            return

        url = normalize_url(story.get("url", ""))
        if not is_valid_url(url):
            log.warning("Invalid URL '%s' — aborting", url)
            return
        story["url"] = url

        # OG metadata (cached from news.json or fetched live — optional, no skip if missing)
        story["og"] = _build_og(story)

        # Write the LinkedIn post
        comment = _build_post(story, client)
        if not comment:
            return

        log.info("Publishing: %s (score %s)", story["title"], story.get("score"))

        # Telegram approval
        if not skip_confirm:
            preview = (
                f"<b>\U0001f4dd Post da pubblicare su LinkedIn</b>\n\n"
                f"<b>{story['title']}</b>\n"
                f"\u2b50 Score: {story.get('score', '?')}/10 • Rank #{story.get('rank', '?')}"
                f" • {story.get('source', '')}\n"
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
            og=story["og"],
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
            "\u2705 <b>LinkedIn post pubblicato!</b>\n\n"
            f"\U0001f4cc <b>{story['title']}</b>\n"
            f"\U0001f3f7 {story.get('source', '')} • "
            f"\u2b50 Score: {story.get('score', 0)}/10 (rank #{story.get('rank', '?')})\n"
            f"\U0001f517 {story['url']}\n\n"
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
