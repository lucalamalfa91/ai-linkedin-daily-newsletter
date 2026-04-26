import logging

import requests

from config import LINKEDIN_API, LINKEDIN_VERSION
from utils.og_meta import fetch_og_meta, upload_linkedin_image

log = logging.getLogger(__name__)


def publish(comment: str, article_url: str, article_title: str, person_id: str, token: str, og: dict | None = None) -> str:
    """Post a public article update to LinkedIn. Returns the post ID."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }

    if og is None:
        og = fetch_og_meta(article_url)
    thumbnail_urn = upload_linkedin_image(og["image"], person_id, token) if og.get("image") else None
    log.info("Article enrichment — thumbnail=%s desc_len=%d", thumbnail_urn, len(og.get("description", "")))

    article: dict = {"source": article_url, "title": article_title}
    if thumbnail_urn:
        article["thumbnail"] = thumbnail_urn
    if og.get("description"):
        article["description"] = og["description"]

    payload: dict = {
        "author": person_id,
        "commentary": comment,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
        "content": {"article": article},
    }

    resp = requests.post(LINKEDIN_API, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        log.error("LinkedIn error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

    post_id = resp.headers.get("x-restli-id", "unknown")
    log.info("LinkedIn post published — ID: %s", post_id)
    return post_id
