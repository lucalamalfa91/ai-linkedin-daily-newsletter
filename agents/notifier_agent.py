import logging
import time

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


def request_approval(preview_text: str, bot_token: str, chat_id: str, timeout_minutes: int = 30) -> bool:
    """Send an inline-keyboard approval request. Returns True if approved, False on reject or timeout."""
    base = f"https://api.telegram.org/bot{bot_token}"

    # Drain pending updates so stale callbacks from previous runs are ignored.
    try:
        r = requests.post(f"{base}/getUpdates", json={"limit": 100, "timeout": 0}, timeout=10)
        updates = r.json().get("result", [])
        offset = (updates[-1]["update_id"] + 1) if updates else 0
    except Exception:
        offset = 0

    # Send the approval message with inline keyboard buttons.
    try:
        r = requests.post(
            f"{base}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": preview_text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "✅ Pubblica", "callback_data": "approve"},
                        {"text": "❌ Annulla",  "callback_data": "reject"},
                    ]]
                },
            },
            timeout=15,
        )
        r.raise_for_status()
        msg_id = r.json()["result"]["message_id"]
    except Exception as exc:
        log.error("Failed to send approval request: %s", exc)
        return False

    log.info("Waiting for Telegram approval (timeout=%d min, msg_id=%d)", timeout_minutes, msg_id)
    deadline = time.time() + timeout_minutes * 60

    while time.time() < deadline:
        try:
            r = requests.post(
                f"{base}/getUpdates",
                json={"offset": offset, "timeout": 30, "allowed_updates": ["callback_query"]},
                timeout=40,
            )
            updates = r.json().get("result", [])
        except Exception as exc:
            log.warning("getUpdates error: %s", exc)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            cb = update.get("callback_query")
            if not cb:
                continue
            if cb.get("message", {}).get("message_id") != msg_id:
                continue
            decision = cb.get("data", "reject")
            try:
                requests.post(
                    f"{base}/answerCallbackQuery",
                    json={
                        "callback_query_id": cb["id"],
                        "text": "✅ Pubblicazione avviata!" if decision == "approve" else "❌ Annullato",
                    },
                    timeout=10,
                )
            except Exception:
                pass
            log.info("Approval decision: %s", decision)
            return decision == "approve"

    log.warning("Approval timeout after %d minutes", timeout_minutes)
    return False
