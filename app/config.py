from pydantic_settings import BaseSettings

class Env(BaseSettings):
    DATABASE_HOSTNAME: str
    DATABASE_PORT: int
    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str
    # SECRET_KEY: str
    # ALGORITHM: str
    # ACCESS_TOKEN_EXPIRE_MINUTES: str # might not need this

    class Config:
        env_file = ".env"

env = Env()