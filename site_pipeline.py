#!/usr/bin/env python3
"""Daily AI Coding Tools digest pipeline.

Flow:
  1. Scrape changelog pages (8 sources) → Claude Haiku extracts items
  2. Scrape Claude Code feature docs → Claude Sonnet generates spotlight articles
  3. Rank all items → top 3 (Claude Code gets priority boost)
  4. Write summary + considerations for each → news.json + index.html
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

from agents.changelog_agent import extract_changelog_items
from agents.feature_spotlight_agent import generate_feature_spotlight
from agents.ranking_agent import rank_stories
from agents.site_writer_agent import write_site_entry
from config import (
    CHANGELOG_SOURCES,
    CLAUDE_CODE_FEATURE_PAGES,
    CODING_FOCUS_TOPICS,
    NEWS_JSON_PATH,
    RANKED_SITE_TOP_N,
    SITE_OUTPUT_PATH,
    TEMPLATE_PATH,
)
from utils.og_meta import fetch_og_meta
from utils.page_scraper import fetch_page_text
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


def _scrape_changelogs(client: anthropic.Anthropic) -> list[dict]:
    """Scrape all changelog sources and return extracted items."""
    items = []
    for source_name, url in CHANGELOG_SOURCES.items():
        log.info("Scraping changelog: %s", source_name)
        text = fetch_page_text(url)
        if not text:
            log.warning("Empty page for %s — skipping", source_name)
            continue
        extracted = extract_changelog_items(text, source_name, url, client)
        items.extend(extracted)
    log.info("Changelog scraping: %d total items from %d sources", len(items), len(CHANGELOG_SOURCES))
    return items


def _generate_spotlights(client: anthropic.Anthropic) -> list[dict]:
    """Scrape Claude Code feature docs and generate self-made spotlight articles."""
    spotlights = []
    for feature_name, url in CLAUDE_CODE_FEATURE_PAGES:
        log.info("Generating feature spotlight: %s", feature_name)
        text = fetch_page_text(url)
        article = generate_feature_spotlight(feature_name, url, text, client)
        if article:
            spotlights.append(article)
    log.info("Feature spotlights: %d articles generated", len(spotlights))
    return spotlights


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

    # 1. Scrape changelogs from all 8 sources
    changelog_items = _scrape_changelogs(client)

    # 2. Generate Claude Code feature spotlight articles
    spotlight_items = _generate_spotlights(client)

    # Merge: spotlights first so the ranker sees them prominently.
    # The ranking_agent prompt gives +3 to focus topics which includes Claude Code.
    all_items = spotlight_items + changelog_items

    if not all_items:
        log.error("No items collected from any source — aborting")
        sys.exit(1)

    log.info("Total items to rank: %d (%d spotlights + %d changelog)",
             len(all_items), len(spotlight_items), len(changelog_items))

    # 3. Rank: pick top 3
    ranked = rank_stories(
        all_items,
        client,
        focus_topics=CODING_FOCUS_TOPICS,
        top_n=RANKED_SITE_TOP_N,
    )
    if not ranked:
        log.error("Ranking returned no results — aborting")
        sys.exit(1)

    # 4. Enrich top 3 with full summary + considerations
    stories = []
    for candidate in ranked[:RANKED_SITE_TOP_N]:
        url = normalize_url(candidate.get("url", ""))
        if not is_valid_url(url):
            log.warning("Invalid URL for '%s' — skipping", candidate.get("title"))
            continue

        candidate["url"] = url
        original = next((it for it in all_items if it["link"] == url), None)

        og = fetch_og_meta(url)
        enrichment = write_site_entry(candidate, original, client)

        stories.append({
            "rank": candidate.get("rank"),
            "score": candidate.get("score"),
            "title": candidate.get("title", ""),
            "url": url,
            "source": original.get("source", "") if original else "",
            "summary": enrichment["summary"],
            "considerations": enrichment["considerations"],
            "published": original.get("published", "") if original else "",
            "og_image": og.get("image") or None,
            "is_feature_spotlight": bool(original and original.get("_is_feature_spotlight")),
        })

    if not stories:
        log.error("No valid stories after enrichment — aborting")
        sys.exit(1)

    # 5. Write news.json
    now = datetime.now(timezone.utc)
    news_data = {
        "generated_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "stories": stories,
    }
    _write_news_json(news_data)

    # 6. Build HTML
    build_site(news_data, TEMPLATE_PATH, SITE_OUTPUT_PATH)

    # 7. Commit and push (GitHub Actions only)
    _commit_and_push()

    spotlights_in_top3 = sum(1 for s in stories if s.get("is_feature_spotlight"))
    log.info(
        "Site pipeline complete — %d stories (%d feature spotlights, %d changelogs)",
        len(stories), spotlights_in_top3, len(stories) - spotlights_in_top3,
    )


if __name__ == "__main__":
    main()
