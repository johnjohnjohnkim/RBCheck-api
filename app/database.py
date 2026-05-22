from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import os, sqlite3, re

from .config import env

###### For Postgres Database Connection #######

PG_DB_URL = f"postgresql://{env.DATABASE_USERNAME}:{env.DATABASE_PASSWORD}@{env.DATABASE_HOSTNAME}/{env.DATABASE_NAME}"

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

database = os.path.expanduser("~/Library/Messages/chat.db")

conn = sqlite3.connect(database)
litecursor = conn.cursor()
