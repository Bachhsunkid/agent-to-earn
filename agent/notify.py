"""Send a Telegram message to the operator (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID from the environment).

Usage: python3 agent/notify.py "text"   (or pipe the text on stdin)
Never prints the token: errors report only the exception type.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

MAX_LEN = 4000
ATTEMPTS = 3


def send(text: str) -> bool:
    token, chat_id = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("telegram not configured; message not sent", file=sys.stderr)
        return False
    body = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text[:MAX_LEN], "disable_web_page_preview": "true",
    }).encode()
    # Alerts are urgent, and TLS connections to Telegram occasionally drop: retry briefly.
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body,
                                        timeout=15) as resp:
                return bool(json.load(resp).get("ok"))
        except (OSError, ValueError) as exc:
            print(f"telegram send failed (attempt {attempt}): {type(exc).__name__}", file=sys.stderr)
            if attempt < ATTEMPTS:
                time.sleep(5 * attempt)
    return False


if __name__ == "__main__":
    message = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    sys.exit(0 if send(message) else 1)
