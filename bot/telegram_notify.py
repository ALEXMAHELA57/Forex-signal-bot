"""Send messages to a Telegram channel/group/chat through the Bot API.

With no token configured the bot runs in dry-run mode and just logs messages.
"""
import logging
import time

import requests

from . import config

log = logging.getLogger(__name__)


def send_message(text, reply_to=None):
    """Send HTML text. Returns Telegram message_id, or None on failure/dry run."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.info("[DRY RUN - Telegram not configured]\n%s", text)
        return None

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if reply_to:
        payload["reply_parameters"] = {
            "message_id": reply_to,
            "allow_sending_without_reply": True,
        }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return data["result"]["message_id"]
            log.warning("Telegram error: %s", data.get("description"))
            if resp.status_code == 429:
                time.sleep(data.get("parameters", {}).get("retry_after", 5))
                continue
            if resp.status_code in (400, 401, 403):
                return None  # bad token / chat id / permissions: retrying won't help
        except (requests.RequestException, ValueError) as exc:
            log.warning("Telegram request failed: %s", exc)
        time.sleep(2 * (attempt + 1))
    return None
