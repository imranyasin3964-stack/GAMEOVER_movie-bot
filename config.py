import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID: int = int(os.getenv("API_ID") or 0)
    API_HASH: str = os.getenv("API_HASH", "")
    BOT_TOKEN: str = os.getenv("TOKEN", "")
    STRING3: str = os.getenv("STRING3", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID") or 0)

    DOWNLOADS_DIR: str = os.getenv("DOWNLOADS_DIR", "downloads")
    PROJECT_ROOT: str = os.path.dirname(os.path.abspath(__file__))

    BOT_NAME: str = "GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ"
    BOT_USERNAME: str = ""

    @staticmethod
    def validate():
        missing = []
        if not Config.API_ID:
            missing.append("API_ID")
        if not Config.API_HASH:
            missing.append("API_HASH")
        if not Config.BOT_TOKEN:
            missing.append("TOKEN (Bot Token)")
        if not Config.STRING3:
            missing.append("STRING3 (String Session)")

        if missing:
            raise ValueError(
                f"\n\nError: .env mein ye fields khali hain:\n" +
                "\n".join(f"  - {m}" for m in missing) +
                "\n\nPehle .env fill karo phir bot chalao!\n"
            )
