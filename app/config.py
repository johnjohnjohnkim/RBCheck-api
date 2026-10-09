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
    # Only used by the iMessage ingestion scripts.
    RBC_HANDLE_ID: str = "72272"
    RBC_CHATDB_PATH: str | None = None

    @property
    def db_host(self) -> str:
        return self.IP_ADDRESS or self.DATABASE_HOSTNAME


env = Env()
