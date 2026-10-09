from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base

import os, sys, sqlite3

from .config import env

##### For Postgres Database Connection #######

# URL.create escapes special characters in the password
PG_DB_URL = URL.create(
    "postgresql+psycopg",
    username=env.DATABASE_USERNAME,
    password=env.DATABASE_PASSWORD,
    host=env.db_host,
    port=env.DATABASE_PORT,
    database=env.DATABASE_NAME,
)

# The session timezone makes Postgres read the naive local times we store (and the
# naive day boundaries we query with) as TIMEZONE, wherever the server runs.
engine = create_engine(
    PG_DB_URL,
    pool_pre_ping=True,
    connect_args={"options": f"-c timezone={env.TIMEZONE}"},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


####### For SQLite "Chat.db" Connection #######
# Opened on demand by the ingestion scripts only, so the API can run anywhere.

def chat_db_path() -> str:
    if env.RBC_CHATDB_PATH:
        return env.RBC_CHATDB_PATH
    if sys.platform == "win32":
        # For testing on Windows, you must have a copy of the database from copy_chat_db.py!!
        return os.path.join(os.path.dirname(__file__), '..', 'transactions.db')
    return os.path.expanduser("~/Library/Messages/chat.db")


def open_chat_db() -> sqlite3.Connection:
    return sqlite3.connect(chat_db_path())
