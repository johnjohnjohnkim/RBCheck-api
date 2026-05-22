from pydantic_settings import BaseSettings

class Env(BaseSettings):
    DATABASE_HOSTNAME: str
    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str
    DATABASE_PORT: str
    SECRET_KEY: str
    # ALGORITHM: str
    # ACCESS_TOKEN_EXPIRE_MINUTES: str # might not need this

    class config:
        env_file = ".env"

env = Env()