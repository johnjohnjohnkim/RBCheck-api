import os

# app.config reads these at import; the tests never connect to Postgres.
for key, value in {
    "DATABASE_HOSTNAME": "localhost",
    "DATABASE_PORT": "5432",
    "DATABASE_USERNAME": "test",
    "DATABASE_PASSWORD": "test",
    "DATABASE_NAME": "test",
    "READ_TOKEN": "test-read-token-0123456789abcdef",
    "WRITE_TOKEN": "test-write-token-0123456789abcdef",
    "CORS_ORIGINS": "https://site.example,http://127.0.0.1:3000",
}.items():
    os.environ.setdefault(key, value)

READ_TOKEN = os.environ["READ_TOKEN"]
WRITE_TOKEN = os.environ["WRITE_TOKEN"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
