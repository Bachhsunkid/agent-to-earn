"""Find the chat_id of whoever messaged the bot and store it in .env as TELEGRAM_CHAT_ID.

Message the bot once in Telegram, then run this while the trading bot is stopped
(Telegram allows only one getUpdates consumer per token). Prints only chat ids.
"""

import json
import sys
import urllib.request

from init_env import read_env, update_env


def main() -> int:
    token = read_env().get("TELEGRAM_TOKEN", "")
    if not token:
        print("TELEGRAM_TOKEN is empty in .env")
        return 1
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15) as r:
        updates = json.load(r).get("result", [])
    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat")
        if chat and chat.get("type") == "private":
            chats[str(chat["id"])] = chat.get("type")
    if not chats:
        print("no private chat found; send the bot a message first")
        return 1
    if len(chats) > 1:
        print(f"several private chats found: {', '.join(chats)}; set TELEGRAM_CHAT_ID manually")
        return 1
    chat_id = next(iter(chats))
    update_env({"TELEGRAM_CHAT_ID": chat_id})
    print(f"TELEGRAM_CHAT_ID set to {chat_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
