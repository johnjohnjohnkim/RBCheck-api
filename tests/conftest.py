import os

# app.config reads these at import; the tests never connect to Postgres.
for key, value in {
    "DATABASE_HOSTNAME": "localhost",
    "DATABASE_PORT": "5432",
    "DATABASE_USERNAME": "test",
    "DATABASE_PASSWORD": "test",
    "DATABASE_NAME": "test",
}.items():
    os.environ.setdefault(key, value)
