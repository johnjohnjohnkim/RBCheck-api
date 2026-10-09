from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "app/.env"), extra="ignore")

    DATABASE_HOSTNAME: str
    DATABASE_PORT: int
    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str
    # Optional override kept for existing .env files that connect by IP.
    IP_ADDRESS: str | None = None
    # The zone the bank texts are written in. Decides what "today" means and how
    # the database reads naive timestamps, so it must not depend on the server.
    TIMEZONE: str = "America/Toronto"
    # Only used by the iMessage ingestion scripts.
    RBC_HANDLE_ID: str = "72272"
    RBC_CHATDB_PATH: str | None = None

    @field_validator("TIMEZONE")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @property
    def db_host(self) -> str:
        return self.IP_ADDRESS or self.DATABASE_HOSTNAME


env = Env()
