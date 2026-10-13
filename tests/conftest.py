"""
Tests run against a real Postgres database, because ingest relies on
Postgres-only SQL. Point them at one with TEST_DATABASE_* variables; by
default they use rbcheck_test on localhost, creating it if needed.
Every table is emptied before each test, so the name must end in _test.
"""

import getpass
import os

import psycopg

TEST_DB = {
    "DATABASE_HOSTNAME": os.environ.get("TEST_DATABASE_HOSTNAME", "localhost"),
    "DATABASE_PORT": os.environ.get("TEST_DATABASE_PORT", "5432"),
    "DATABASE_USERNAME": os.environ.get("TEST_DATABASE_USERNAME", getpass.getuser()),
    "DATABASE_PASSWORD": os.environ.get("TEST_DATABASE_PASSWORD", ""),
    "DATABASE_NAME": os.environ.get("TEST_DATABASE_NAME", "rbcheck_test"),
}
assert TEST_DB["DATABASE_NAME"].endswith("_test"), "Refusing to run tests against a non-test database"

# Settings are read when the app is imported, so these must be set first.
os.environ.update(TEST_DB)
os.environ.update({
    "INGEST_API_KEY": "test-ingest-key",
    "TIMEZONE": "America/Toronto",
})

def _create_test_database():
    with psycopg.connect(
        host=TEST_DB["DATABASE_HOSTNAME"], port=TEST_DB["DATABASE_PORT"],
        user=TEST_DB["DATABASE_USERNAME"], password=TEST_DB["DATABASE_PASSWORD"],
        dbname="postgres", autocommit=True,
    ) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB["DATABASE_NAME"],)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB["DATABASE_NAME"]}"')

_create_test_database()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.main import app

INGEST_HEADERS = {"X-Ingest-Key": "test-ingest-key"}


@pytest.fixture(autouse=True)
def empty_tables():
    with TestClient(app):
        pass  # Runs startup, which creates the tables.
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE transactions, daily_digests RESTART IDENTITY"))


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
