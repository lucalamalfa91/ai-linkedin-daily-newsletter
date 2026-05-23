#!/usr/bin/env python3
"""Daily AI newsletter digest pipeline.

Flow:
  1. Fetch RSS feeds (opinionated AI bloggers/writers)
  2. For each post: extract the PRIMARY source they're discussing (not the blogger's URL)
  3. Deduplicate — multiple bloggers covering the same story → one entry
  4. Rank with Claude Haiku (AI-only filter applied)
  5. Enrich top 5 with summary + considerations (La Malfa format)
  6. Write news.json + index.html
  7. Commit + push → Vercel auto-deploys
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
from agents.source_extractor_agent import extract_original_source
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

    # 1. Fetch RSS feeds — last 7 days from all configured blogger sources
    raw_items = fetch_feeds(days=7)
    if not raw_items:
        log.error("No items from RSS feeds — aborting")
        sys.exit(1)
    log.info("RSS feeds: %d raw items collected", len(raw_items))

    # 2. Extract primary source for each blogger post
    #    (e.g. Ethan Mollick writes about GPT-5 → we use openai.com/blog/gpt-5)
    #    Items with no clear primary source are kept with their original URL.
    all_items: list[dict] = []
    seen_extracted: set[str] = set()

    for item in raw_items:
        original = extract_original_source(item, client)
        if original:
            url = normalize_url(original["url"])
            if url in seen_extracted:
                log.debug("Dedup: multiple bloggers covered same source — skipping '%s'", url)
                continue
            seen_extracted.add(url)
            enriched = dict(item)
            enriched["link"] = url
            enriched["title"] = original["title"] or item["title"]
            enriched["source"] = original["source_name"] or item["source"]
            enriched["blogger_context"] = item["summary"]  # original blogger analysis as context
            all_items.append(enriched)
        else:
            # Blogger's own analysis — use as-is (original content, not a reaction)
            all_items.append(item)

    log.info("After source extraction: %d unique items", len(all_items))

    # 3. Rank with Claude Haiku — AI-only focus enforced via FOCUS_TOPICS
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

        # Use blogger's analysis as context if available, otherwise use RSS summary
        if original and original.get("blogger_context"):
            context_item = dict(original)
            context_item["summary"] = original["blogger_context"]
        else:
            context_item = original

        enrichment = write_site_entry(candidate, context_item, client)

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
