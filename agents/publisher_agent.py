import logging

import requests

from config import LINKEDIN_API, LINKEDIN_DOCUMENTS_API, LINKEDIN_VERSION
from utils.og_meta import fetch_og_meta, upload_linkedin_image

log = logging.getLogger(__name__)


def _linkedin_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }


def _post_to_linkedin(payload: dict, token: str) -> str:
    resp = requests.post(LINKEDIN_API, headers=_linkedin_headers(token), json=payload, timeout=30)
    if not resp.ok:
        log.error("LinkedIn error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
    post_id = resp.headers.get("x-restli-id", "unknown")
    log.info("LinkedIn post published — ID: %s", post_id)
    return post_id


def publish(comment: str, article_url: str, article_title: str, person_id: str, token: str, og: dict | None = None) -> str:
    """Post a public article update to LinkedIn. Returns the post ID."""
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
    return _post_to_linkedin(payload, token)


def publish_text(comment: str, person_id: str, token: str) -> str:
    """Post a native text-only update to LinkedIn (no article card). Returns the post ID."""
    payload: dict = {
        "author": person_id,
        "commentary": comment,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    return _post_to_linkedin(payload, token)


def upload_document(pdf_bytes: bytes, person_id: str, token: str) -> str:
    """Upload a PDF to LinkedIn Documents API. Returns the document URN."""
    headers = _linkedin_headers(token)
    init_payload = {"initializeUploadRequest": {"owner": person_id}}
    resp = requests.post(LINKEDIN_DOCUMENTS_API, headers=headers, json=init_payload, timeout=30)
    if not resp.ok:
        log.error("LinkedIn documents init error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
    data = resp.json()
    upload_url = data["value"]["uploadUrl"]
    document_urn = data["value"]["document"]
    log.info("Document upload initialized — URN: %s", document_urn)

    put_resp = requests.put(
        upload_url,
        data=pdf_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=60,
    )
    if not put_resp.ok:
        log.error("LinkedIn document PUT error %s: %s", put_resp.status_code, put_resp.text)
        put_resp.raise_for_status()
    log.info("Document uploaded successfully (%d bytes)", len(pdf_bytes))
    return document_urn


def publish_carousel(comment: str, document_urn: str, title: str, person_id: str, token: str) -> str:
    """Post a document/carousel post to LinkedIn. Returns the post ID."""
    payload: dict = {
        "author": person_id,
        "commentary": comment,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
        "content": {
            "media": {
                "id": document_urn,
                "title": title,
            }
        },
    }
    return _post_to_linkedin(payload, token)
