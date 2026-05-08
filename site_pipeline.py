#!/usr/bin/env python3
"""Daily AI Coding Tools digest pipeline.

Flow: fetch coding tool feeds → rank top 3 → write summaries + considerations
      → write site/news.json → build site/index.html → commit + push.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agents.feed_agent import fetch_feeds
from agents.ranking_agent import rank_stories
from agents.site_writer_agent import write_site_entry
from config import (
    CODING_FOCUS_TOPICS,
    CODING_RSS_FEEDS,
    NEWS_JSON_PATH,
    RANKED_SITE_TOP_N,
    SITE_OUTPUT_PATH,
    TEMPLATE_PATH,
)
from utils.cursor_scraper import fetch_cursor_changelog
from utils.og_meta import fetch_og_meta
from utils.site_builder import build_site
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


def _write_news_json(data: dict) -> None:
    """Atomically write news.json."""
    path = Path(NEWS_JSON_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(data, tf, ensure_ascii=False, indent=2)
        tmp_path = tf.name
    Path(tmp_path).replace(path)
    log.info("Wrote %s", path)


def _commit_and_push() -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        log.info("Skipping git commit (not in GitHub Actions)")
        return
    cmds = [
        ["git", "config", "user.email", "actions@github.com"],
        ["git", "config", "user.name", "GitHub Actions"],
        ["git", "add", str(NEWS_JSON_PATH), str(SITE_OUTPUT_PATH)],
    ]
    for cmd in cmds:
        subprocess.run(cmd, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        log.info("No changes to commit")
        return
    subprocess.run(
        ["git", "commit", "-m", "chore: update site digest [skip ci]"],
        check=True,
    )
    subprocess.run(["git", "push"], check=True)
    log.info("Committed and pushed site digest")


def main() -> None:
    _load_env()
    _require_env("ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 1. Fetch last 2 days from coding tool feeds; widen window if too sparse
    items = fetch_feeds(days=2, feeds=CODING_RSS_FEEDS)
    if len(items) < RANKED_SITE_TOP_N:
        log.info("Only %d items in 2 days — widening to 4 days", len(items))
        items = fetch_feeds(days=4, feeds=CODING_RSS_FEEDS)

    # Also add Cursor changelog (no RSS)
    cursor_items = fetch_cursor_changelog(limit=3)
    items = cursor_items + items  # Cursor first so it's not excluded by feed list order

    if not items:
        log.warning("No items fetched from any source — aborting")
        sys.exit(1)

    log.info("Total items to rank: %d", len(items))

    # 2. Rank: top 3 via Claude Haiku
    ranked = rank_stories(
        items,
        client,
        focus_topics=CODING_FOCUS_TOPICS,
        top_n=RANKED_SITE_TOP_N,
    )
    if not ranked:
        log.error("Ranking returned no results — aborting")
        sys.exit(1)

    # 3. Enrich each story with summary + considerations
    stories = []
    for candidate in ranked[:RANKED_SITE_TOP_N]:
        url = normalize_url(candidate.get("url", ""))
        if not is_valid_url(url):
            log.warning("Invalid URL for candidate '%s' — skipping", candidate.get("title"))
            continue

        candidate["url"] = url
        original = next((it for it in items if it["link"] == url), None)

        og = fetch_og_meta(url)
        enrichment = write_site_entry(candidate, original, client)

        stories.append({
            "rank": candidate.get("rank"),
            "score": candidate.get("score"),
            "title": candidate.get("title", ""),
            "url": url,
            "source": original.get("source", "") if original else candidate.get("source", ""),
            "summary": enrichment["summary"],
            "considerations": enrichment["considerations"],
            "published": original.get("published", "") if original else "",
            "og_image": og.get("image") or None,
        })

    if not stories:
        log.error("No valid stories after enrichment — aborting")
        sys.exit(1)

    # 4. Write news.json
    now = datetime.now(timezone.utc)
    news_data = {
        "generated_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "stories": stories,
    }
    _write_news_json(news_data)

    # 5. Build HTML
    build_site(news_data, TEMPLATE_PATH, SITE_OUTPUT_PATH)

    # 6. Commit and push (GitHub Actions only)
    _commit_and_push()

    log.info("Site pipeline complete — %d stories published", len(stories))


if __name__ == "__main__":
    main()
