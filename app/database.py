from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base

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
