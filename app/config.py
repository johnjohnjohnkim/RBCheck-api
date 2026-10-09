import re
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator
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
    # Bearer tokens, required: the app refuses to start without them. READ_TOKEN
    # lets a browser read; WRITE_TOKEN is for the Mac poller (and may read too).
    # Generate each with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    READ_TOKEN: str
    WRITE_TOKEN: str
    # Browser origins allowed to call the API, comma separated (no wildcards).
    CORS_ORIGINS: str = "https://gwanwoo.dev"
    # /docs and /openapi.json describe every endpoint; off unless asked for.
    ENABLE_DOCS: bool = False

    @field_validator("READ_TOKEN", "WRITE_TOKEN")
    @classmethod
    def _long_enough(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("tokens must not start or end with whitespace")
        if len(value) < 24:
            raise ValueError("tokens must be at least 24 characters")
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _plain_origins(cls, value: str) -> str:
        for origin in (o.strip() for o in value.split(",") if o.strip()):
            if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?", origin):
                raise ValueError(f"{origin!r} is not a plain origin like https://site.example "
                                 "(no wildcard, path or trailing slash)")
        return value

    @model_validator(mode="after")
    def _distinct_tokens(self):
        if self.READ_TOKEN == self.WRITE_TOKEN:
            raise ValueError("READ_TOKEN and WRITE_TOKEN must differ")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

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
