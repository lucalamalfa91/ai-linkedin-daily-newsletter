#!/usr/bin/env python3
"""Daily AI Coding Tools digest pipeline.

Flow:
  1. Scrape changelog pages (8 sources) → Claude Haiku extracts items
  2. Scrape Claude Code feature docs → Claude Sonnet generates spotlight articles
  3. Rank all items → top 5 (1 slot always Claude Code)
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
    CHANGELOG_SOURCE_HOMEPAGES,
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


def _enforce_claude_code_slot(
    ranked: list[dict],
    all_items: list[dict],
    top_n: int,
) -> list[dict]:
    """Enforce exactly 1 Claude Code item in the top_n results.

    - If 0 CC items: inject the best available one at the last slot.
    - If 2+ CC items: keep only the highest-ranked one, fill remaining slots
      with the next best non-CC items from the ranked pool.
    """
    _cc_sources = {"Claude Code Docs", "Claude Code"}
    cc_links = {it["link"] for it in all_items if it.get("source") in _cc_sources}

    cc_in_pool = [r for r in ranked if r["url"] in cc_links]
    other_in_pool = [r for r in ranked if r["url"] not in cc_links]

    if cc_in_pool:
        best_cc = cc_in_pool[0]
    else:
        cc_item = next(
            (it for it in all_items if it.get("_is_feature_spotlight")), None
        ) or next(
            (it for it in all_items if it.get("source") in _cc_sources), None
        )
        if not cc_item:
            log.warning("No Claude Code item available — omitting guaranteed slot")
            result = other_in_pool[:top_n]
            for i, r in enumerate(result, 1):
                r["rank"] = i
            return result
        best_cc = {"rank": top_n, "score": 5, "title": cc_item["title"], "url": cc_item["link"]}
        log.info("Injected Claude Code item: '%s'", best_cc["title"])

    result = other_in_pool[: top_n - 1] + [best_cc]
    for i, r in enumerate(result, 1):
        r["rank"] = i

    if len(cc_in_pool) > 1:
        log.info("Capped Claude Code from %d to 1 item in top %d", len(cc_in_pool), top_n)

    return result


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

    all_items = spotlight_items + changelog_items

    if not all_items:
        log.error("No items collected from any source — aborting")
        sys.exit(1)

    log.info("Total items to rank: %d (%d spotlights + %d changelog)",
             len(all_items), len(spotlight_items), len(changelog_items))

    # 3. Rank: ask for ALL items so Haiku never drops any by implicit quality threshold
    ranked = rank_stories(
        all_items,
        client,
        focus_topics=CODING_FOCUS_TOPICS,
        top_n=len(all_items),
    )
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
    ranked = deduped

    # Enforce exactly 1 Claude Code slot in the final top N
    ranked = _enforce_claude_code_slot(ranked, all_items, RANKED_SITE_TOP_N)

    # Pad with remaining all_items if fewer than top_n unique items came back
    if len(ranked) < RANKED_SITE_TOP_N:
        used_urls = {normalize_url(r["url"]) for r in ranked}
        for item in all_items:
            if len(ranked) >= RANKED_SITE_TOP_N:
                break
            u = normalize_url(item.get("link", ""))
            if u and u not in used_urls and is_valid_url(u):
                ranked.append({
                    "rank": len(ranked) + 1,
                    "score": 5,
                    "title": item["title"],
                    "url": u,
                })
                used_urls.add(u)
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
        log.info("Padded ranked list to %d items from all_items pool", len(ranked))

    # 4. Enrich top 5 with full summary + considerations
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
        if not og.get("image") and source_name:
            fallback_url = CHANGELOG_SOURCE_HOMEPAGES.get(source_name)
            if fallback_url:
                og = fetch_og_meta(fallback_url)
                if og.get("image"):
                    log.info("Used homepage fallback image for '%s'", source_name)

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

    spotlights_in_top = sum(1 for s in stories if s.get("is_feature_spotlight"))
    log.info(
        "Site pipeline complete — %d stories (%d feature spotlights, %d changelogs)",
        len(stories), spotlights_in_top, len(stories) - spotlights_in_top,
    )


if __name__ == "__main__":
    main()
