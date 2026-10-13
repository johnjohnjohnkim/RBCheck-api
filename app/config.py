from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_HOSTNAME: str
    DATABASE_PORT: int
    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    # Shared secret the Mac ingest agent sends in the X-Ingest-Key header.
    INGEST_API_KEY: str

    # The day boundaries for "today", "this week" and "this month", and the
    # zone times are returned in. Independent of the server's own clock zone.
    TIMEZONE: str = "America/Toronto"

    @field_validator("TIMEZONE")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        # A typo fails at startup, not on the first request.
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {value!r}") from None
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

env = Env()
