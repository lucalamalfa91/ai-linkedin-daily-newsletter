import json
import logging
import os
import re
import subprocess

from config import HISTORY_FILE

log = logging.getLogger(__name__)


def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        log.warning("history.json unreadable (%s) — starting fresh", exc)
        return {}


def save_history(history: dict) -> None:
    tmp = HISTORY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, HISTORY_FILE)
        log.info("history.json saved (%d entries)", len(history))
    except Exception as exc:
        log.warning("Failed to save history.json: %s", exc)


def commit_history_to_git() -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        log.info("Not in GitHub Actions — skipping git commit of history.json")
        return
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "GitHub Actions"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "history.json"], cwd=root, check=True, capture_output=True)
        changed = subprocess.run(
            ["git", "status", "--porcelain", "history.json"],
            cwd=root, capture_output=True, text=True,
        )
        if not changed.stdout.strip():
            log.info("history.json unchanged — nothing to commit")
            return
        subprocess.run(
            ["git", "commit", "-m", "chore: update history.json [skip ci]"],
            cwd=root, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=root, check=True, capture_output=True)
        log.info("history.json committed and pushed")
    except Exception as exc:
        log.warning("git commit of history.json failed: %s", exc)


def extract_topics(title: str, comment: str) -> list[str]:
    _stop = {
        "the", "and", "for", "with", "this", "that", "from", "have", "been",
        "will", "are", "its", "how", "new", "more", "what", "can", "about",
        "your", "our", "just", "also", "they", "when", "into", "some",
    }
    text = (title + " " + comment).lower()
    seen: set[str] = set()
    result: list[str] = []
    for w in re.findall(r"\b[a-z]{4,15}\b", text):
        if w not in _stop and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:15]


def extract_hashtags(comment: str) -> list[str]:
    return re.findall(r"#\w+", comment)
