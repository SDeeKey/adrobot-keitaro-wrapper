import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./adrobot.db"
    keitaro_url: str = "https://tracker.example.com"
    api_key: str = ""
    prefix: str = "test_shmelev_"
    demo_mode: bool = True

    @classmethod
    def from_env(cls):
        load_dotenv()
        settings = cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            keitaro_url=os.getenv("KEITARO_URL", cls.keitaro_url).rstrip("/"),
            api_key=os.getenv("KEITARO_API_KEY", ""),
            prefix=os.getenv("CAMPAIGN_PREFIX", cls.prefix),
            demo_mode=os.getenv("DEMO_MODE", "true").lower() == "true",
        )
        if not settings.prefix.startswith("test_") or not settings.prefix.endswith("_"):
            raise ValueError("CAMPAIGN_PREFIX должен иметь вид test_фамилия_")
        if not settings.demo_mode:
            parsed = urlsplit(settings.keitaro_url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
                raise ValueError("KEITARO_URL должен быть HTTPS-адресом трекера без /admin")
            if not settings.api_key:
                raise ValueError("Заполните KEITARO_API_KEY или включите DEMO_MODE")
        return settings
