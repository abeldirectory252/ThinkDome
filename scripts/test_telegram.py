#!/usr/bin/env python3
"""Interactive test script for Telegram Bot operations (DM, Group, Channel)."""

import asyncio
import json
import sys
from thinkdome.core.config import get_settings
from thinkdome.platform.orchestration.tools import registry

async def main():
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        sys.exit(1)

    print("==================================================")
    print("      ThinkDome Telegram Tools Test Suite         ")
    print("==================================================")

    # 1. Fetch updates
    get_updates = registry.get_tool("telegram_get_updates")
    send_msg = registry.get_tool("send_telegram")

    res = await get_updates.func({"limit": 10})
    data = json.loads(res)
    updates = data.get("updates", [])

    print(f"Pending/Recent updates found: {len(updates)}")
    known_chats = {}
    for upd in updates:
        chat = upd.get("chat", {})
        sender = upd.get("sender", {})
        cid = str(chat.get("id"))
        ctype = chat.get("type")
        name = chat.get("title") or sender.get("username") or sender.get("first_name") or cid
        known_chats[cid] = {"type": ctype, "name": name}

    if known_chats:
        print("\nDiscovered chats:")
        for cid, info in known_chats.items():
            print(f"  • Chat ID: {cid} | Type: {info['type']} | Name: {info['name']}")
    else:
        print("\nNo messages received yet by @thinklite_bot.")
        print("To test:")
        print(" 1. Open Telegram and search for @thinklite_bot")
        print(" 2. Press START (or send a message to the bot)")
        print(" 3. (Optional) Add @thinklite_bot to a group or channel as admin")

if __name__ == "__main__":
    asyncio.run(main())
