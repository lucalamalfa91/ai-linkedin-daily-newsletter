import logging
from html.parser import HTMLParser
from urllib.request import Request, urlopen

import requests

from config import LINKEDIN_IMAGES_API, LINKEDIN_VERSION

log = logging.getLogger(__name__)


def fetch_og_meta(url: str) -> dict:
    """Return og:image and og:description from url. Returns {} on any failure."""
    class _OGParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.image = ""
            self.description = ""

        def handle_starttag(self, tag, attrs):
            if tag != "meta":
                return
            attr = dict(attrs)
            prop = attr.get("property", "") or attr.get("name", "")
            content = attr.get("content", "").strip()
            if not content:
                return
            if prop == "og:image" and not self.image:
                self.image = content
            elif prop == "og:description" and not self.description:
                self.description = content

    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ai-post-bot/1.0)"})
        with urlopen(req, timeout=10) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "text/html" not in ct:
                return {}
            html = resp.read(512_000).decode("utf-8", errors="replace")
        parser = _OGParser()
        parser.feed(html)
        result: dict = {}
        if parser.image.startswith("http"):
            result["image"] = parser.image
        if parser.description:
            desc = parser.description
            if len(desc) > 250:
                desc = desc[:250].rsplit(" ", 1)[0] + "…"
            result["description"] = desc
        return result
    except Exception as exc:
        log.warning("OG meta fetch failed for %s: %s", url, exc)
        return {}


def upload_linkedin_image(image_url: str, person_id: str, token: str) -> str | None:
    """Upload image to LinkedIn Images API. Returns image URN or None on any failure."""
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }
    try:
        img_resp = requests.get(image_url, timeout=10)
        if not img_resp.ok:
            log.warning("Image download failed (%s): %s", img_resp.status_code, image_url)
            return None
        content_type = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            log.warning("Unexpected Content-Type '%s' for image URL", content_type)
            return None
        image_bytes = img_resp.content
        if len(image_bytes) > 5_242_880:
            log.warning("Image too large (%d bytes > 5 MB) — skipping thumbnail", len(image_bytes))
            return None
    except Exception as exc:
        log.warning("Image download error: %s", exc)
        return None

    try:
        init_resp = requests.post(
            LINKEDIN_IMAGES_API,
            headers={**auth_headers, "Content-Type": "application/json"},
            json={"initializeUploadRequest": {"owner": person_id}},
            timeout=15,
        )
        if not init_resp.ok:
            log.warning("LinkedIn image init failed (%s): %s", init_resp.status_code, init_resp.text)
            return None
        value = init_resp.json()["value"]
        upload_url: str = value["uploadUrl"]
        image_urn: str = value["image"]
    except Exception as exc:
        log.warning("LinkedIn image init error: %s", exc)
        return None

    try:
        put_resp = requests.put(
            upload_url,
            data=image_bytes,
            headers={"Content-Type": content_type},
            timeout=30,
        )
        if not put_resp.ok:
            log.warning("LinkedIn image PUT failed (%s)", put_resp.status_code)
            return None
    except Exception as exc:
        log.warning("LinkedIn image PUT error: %s", exc)
        return None

    log.info("LinkedIn image uploaded: %s", image_urn)
    return image_urn
