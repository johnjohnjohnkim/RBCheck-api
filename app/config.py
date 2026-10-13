from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_HOSTNAME: str
    DATABASE_PORT: int
    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str

    # Shared secret the Mac ingest agent sends in the X-Ingest-Key header.
    INGEST_API_KEY: str

    # The day boundaries for "today", "this week" and "this month", and the
    # zone times are returned in. Independent of the server's own clock zone.
    TIMEZONE: str = "America/Toronto"

    # Set only on the public demo API: the real database it copies, scrambled,
    # into its own DATABASE_NAME every hour (see app/demo.py).
    DEMO_SOURCE_DATABASE_NAME: str | None = None

    @model_validator(mode="after")
    def _demo_never_overwrites_its_source(self):
        # The demo replaces everything in its own database every hour.
        if self.DEMO_SOURCE_DATABASE_NAME == self.DATABASE_NAME:
            raise ValueError("DEMO_SOURCE_DATABASE_NAME must not be DATABASE_NAME")
        return self

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
