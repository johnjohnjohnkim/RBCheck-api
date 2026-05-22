from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os, sys, sqlite3

from .config import env

##### For Postgres Database Connection #######

PG_DB_URL = f"postgresql+psycopg://{env.DATABASE_USERNAME}:{env.DATABASE_PASSWORD}@{env.DATABASE_HOSTNAME}/{env.DATABASE_NAME}"

engine = create_engine(PG_DB_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


####### For SQLite "Chat.db" Connection #######

if sys.platform == "win32":
    # For testing on Windows, you must have a copy of the database from copy_chat_db.py!!
    database = os.path.join(os.path.dirname(__file__), '..', 'transactions.db')
else:
    database = os.path.expanduser("~/Library/Messages/chat.db")

conn = sqlite3.connect(database)
litecursor = conn.cursor()

def close_db():
    conn.close()