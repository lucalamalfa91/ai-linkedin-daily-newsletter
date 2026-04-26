import logging
from datetime import datetime, timezone

import requests

from config import ANALYTICS_ENDPOINT, ANALYTICS_MAX_AGE_DAYS, ANALYTICS_MIN_AGE_DAYS, LINKEDIN_VERSION

log = logging.getLogger(__name__)


def fetch_post_analytics(post_id: str, token: str) -> dict | None:
    """Fetch reactions, comments, reposts, impressions from LinkedIn Analytics API.

    Returns None on 403 (missing r_member_social scope) or total failure.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    counts = {"reactions": 0, "comments": 0, "reposts": 0, "impressions": 0}
    key_map = {"REACTION": "reactions", "COMMENT": "comments", "REPOST": "reposts", "IMPRESSION": "impressions"}

    for query_type in ("REACTION", "COMMENT", "REPOST", "IMPRESSION"):
        try:
            params = {"q": "memberCreator", "posts[0]": post_id, "queryType": query_type}
            resp = requests.get(ANALYTICS_ENDPOINT, headers=headers, params=params, timeout=15)
            if resp.status_code == 403:
                log.info("Analytics API 403 for %s — r_member_social scope not granted, skipping", post_id)
                return None
            if not resp.ok:
                log.warning("Analytics API %s failed (%s): %s", query_type, resp.status_code, resp.text[:200])
                continue
            elements = resp.json().get("elements", [])
            counts[key_map[query_type]] = sum(el.get("totalCount", 0) for el in elements)
        except Exception as exc:
            log.warning("Analytics fetch error for %s/%s: %s", post_id, query_type, exc)

    eng = counts["reactions"] + counts["comments"] * 2 + counts["reposts"] * 3
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), **counts, "engagement_score": eng}


def update_analytics(history: dict, token: str) -> dict:
    """Fetch analytics for posts 7–21 days old that don't yet have data. Best-effort."""
    now = datetime.now(timezone.utc)
    updated = 0
    for post_id, record in history.items():
        try:
            pub = datetime.fromisoformat(record.get("published_at", ""))
            age_days = (now - pub).days
            if not (ANALYTICS_MIN_AGE_DAYS <= age_days <= ANALYTICS_MAX_AGE_DAYS):
                continue
            if record.get("analytics") is not None:
                continue
            log.info("Fetching analytics for post %s (age=%dd)", post_id, age_days)
            analytics = fetch_post_analytics(post_id, token)
            if analytics is not None:
                record["analytics"] = analytics
                updated += 1
        except Exception as exc:
            log.warning("Error updating analytics for %s: %s", post_id, exc)
    if updated:
        log.info("Analytics updated for %d posts", updated)
    return history


def compute_performance_bonuses(history: dict) -> str:
    """Return adaptive ranking bonus string from post history, or '' if insufficient data."""
    source_scores: dict[str, list[int]] = {}
    topic_scores: dict[str, list[int]] = {}

    for record in history.values():
        analytics = record.get("analytics")
        if not analytics:
            continue
        eng = analytics.get("engagement_score", 0)
        source = record.get("source", "")
        if source:
            source_scores.setdefault(source, []).append(eng)
        for topic in record.get("topics", []):
            topic_scores.setdefault(topic, []).append(eng)

    if len(source_scores) < 2:
        return ""

    source_means = {src: sum(v) / len(v) for src, v in source_scores.items()}
    overall_mean = sum(source_means.values()) / len(source_means)
    if overall_mean == 0:
        return ""

    high_sources = sorted(s for s, v in source_means.items() if v >= overall_mean * 1.3)
    low_sources = sorted(s for s, v in source_means.items() if v <= overall_mean * 0.6)

    topic_means = {t: sum(v) / len(v) for t, v in topic_scores.items() if len(v) >= 2}
    top_topics = sorted(
        (t for t, v in topic_means.items() if v > overall_mean),
        key=lambda t: -topic_means[t],
    )[:8]

    parts = []
    if high_sources:
        parts.append(f"HISTORICAL PERFORMANCE BONUS — apply +1 to stories from: {', '.join(high_sources)}")
    if low_sources:
        parts.append(f"HISTORICAL PERFORMANCE PENALTY — apply -1 to stories from: {', '.join(low_sources)}")
    if top_topics:
        parts.append(f"HIGH-ENGAGEMENT TOPICS (apply +1 if covered): {', '.join(top_topics)}")
    return "\n".join(parts)
