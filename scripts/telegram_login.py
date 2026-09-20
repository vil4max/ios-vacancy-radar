#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a Telethon StringSession for iOS Hunter Telegram collectors."
    )
    parser.add_argument("--api-id", default=os.environ.get("TELEGRAM_API_ID", "").strip())
    parser.add_argument("--api-hash", default=os.environ.get("TELEGRAM_API_HASH", "").strip())
    parser.add_argument(
        "--phone",
        default=os.environ.get("TELEGRAM_PHONE", "").strip(),
        help="Phone in international format, e.g. +380...",
    )
    args = parser.parse_args()

    api_id = args.api_id or input("TELEGRAM_API_ID: ").strip()
    api_hash = args.api_hash or input("TELEGRAM_API_HASH: ").strip()
    if not api_id or not api_hash:
        print("api_id and api_hash are required", file=sys.stderr)
        return 1

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("Install deps first: pip install -r requirements.txt", file=sys.stderr)
        return 1

    async def _login() -> str:
        from telethon.errors import SessionPasswordNeededError

        client = TelegramClient(StringSession(), int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            phone = args.phone or (await asyncio.to_thread(input, "Phone (+380...): ")).strip()
            await client.send_code_request(phone)
            code = (await asyncio.to_thread(input, "Code from Telegram: ")).strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = await asyncio.to_thread(getpass, "2FA password: ")
                await client.sign_in(password=password)
        session = client.session.save()
        await client.disconnect()
        return session

    session = asyncio.run(_login())
    print()
    print("Add this GitHub Actions secret:")
    print("  Name: TELEGRAM_SESSION")
    print("  Value:")
    print(session)
    print()
    print("Also set TELEGRAM_API_ID and TELEGRAM_API_HASH as repository secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
