#!/usr/bin/env python3
"""Daily AI newsletter digest pipeline.

Flow:
  1. Fetch RSS feeds (opinionated AI writers + labs)
  2. Rank all items with Claude Haiku
  3. Enrich top 5 with summary + considerations (La Malfa format)
  4. Write news.json + index.html
  5. Commit + push → Vercel auto-deploys
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
    FOCUS_TOPICS,
    NEWS_JSON_PATH,
    RANKED_SITE_TOP_N,
    SITE_OUTPUT_PATH,
    TEMPLATE_PATH,
)
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

    # 1. Fetch RSS feeds — last 7 days from all configured sources
    all_items = fetch_feeds(days=7)
    if not all_items:
        log.error("No items from RSS feeds — aborting")
        sys.exit(1)
    log.info("RSS feeds: %d items collected", len(all_items))

    # 2. Rank all items with Claude Haiku
    ranked = rank_stories(all_items, client, focus_topics=FOCUS_TOPICS, top_n=len(all_items))
    if not ranked:
        log.error("Ranking returned no results — aborting")
        sys.exit(1)

    # Deduplicate by URL (keep highest-ranked per URL)
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for r in ranked:
        u = normalize_url(r.get("url", ""))
        if u not in seen_urls:
            seen_urls.add(u)
            deduped.append(r)
    for i, r in enumerate(deduped, 1):
        r["rank"] = i
    ranked = deduped

    # 3. Enrich top N with summary + considerations (La Malfa format)
    stories = []
    for candidate in ranked[:RANKED_SITE_TOP_N]:
        url = normalize_url(candidate.get("url", ""))
        if not is_valid_url(url):
            log.warning("Invalid URL for '%s' — skipping", candidate.get("title"))
            continue

        candidate["url"] = url
        title = candidate.get("title", "")
        original = (
            next((it for it in all_items if it["link"] == url and it["title"] == title), None)
            or next((it for it in all_items if it["link"] == url), None)
        )

        source_name = original.get("source", "") if original else ""
        og = fetch_og_meta(url)
        enrichment = write_site_entry(candidate, original, client)

        stories.append({
            "rank": candidate.get("rank"),
            "score": candidate.get("score"),
            "title": candidate.get("title", ""),
            "url": url,
            "source": source_name,
            "summary": enrichment["summary"],
            "considerations": enrichment["considerations"],
            "published": original.get("published", "") if original else "",
            "og_image": og.get("image") or None,
            "is_feature_spotlight": False,
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

    log.info("Site pipeline complete — %d stories from RSS feeds", len(stories))


if __name__ == "__main__":
    main()
