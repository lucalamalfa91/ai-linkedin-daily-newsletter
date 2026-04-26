import logging
import re

log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Return a valid https:// URL, converting arXiv identifiers and DOIs."""
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    arxiv_match = re.match(r"(?i)^arxiv:(\S+)$", url.strip())
    if arxiv_match:
        return f"https://arxiv.org/abs/{arxiv_match.group(1)}"
    if re.match(r"^10\.\d{4,}/", url.strip()):
        return f"https://doi.org/{url.strip()}"
    log.warning("Could not normalise URL '%s' — treating as empty", url)
    return ""


def is_valid_url(url: str) -> bool:
    return bool(url) and url.startswith("https://")
