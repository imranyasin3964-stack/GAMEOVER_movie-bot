"""
Generate a new Pyrogram String Session for GAMEOVER MOVIE HUB.
Run this script ONCE to generate STRING3, then add it to .env
"""

import asyncio
from pyrogram import Client
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")

async def main():
    print("=" * 50)
    print("  GAMEOVER MOVIE HUB — String Session Generator")
    print("=" * 50)
    print("Apna phone number enter karein (with country code, e.g. +923001234567)")
    print()

    async with Client(
        "generate_session_temp",
        api_id=API_ID,
        api_hash=API_HASH,
    ) as session_app:
        string_session = await session_app.export_session_string()

    print()
    print("=" * 50)
    print("✅ STRING3 successfully generated!")
    print()
    print("Niche ki value copy karein aur .env me STRING3 ke saamne paste karein:")
    print()
    print(string_session)
    print()
    print("=" * 50)

    # Cleanup temp session file
    import os
    for f in os.listdir("."):
        if f.startswith("generate_session_temp"):
            os.remove(f)

if __name__ == "__main__":
    asyncio.run(main())
