import logging

import requests

log = logging.getLogger(__name__)


def send(text: str, bot_token: str, chat_id: str) -> None:
    """Send a Telegram message. Best-effort — never raises."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Telegram notification sent")
    except Exception as exc:
        log.warning("Telegram notification failed: %s", exc)
