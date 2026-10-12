from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings

class Env(BaseSettings):
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

    class Config:
        env_file = ".env"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

env = Env()
