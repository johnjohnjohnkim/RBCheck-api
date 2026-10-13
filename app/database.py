from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import env

def make_engine(database: str):
    url = URL.create(
        "postgresql+psycopg",
        username=env.DATABASE_USERNAME,
        password=env.DATABASE_PASSWORD,
        host=env.DATABASE_HOSTNAME,
        port=env.DATABASE_PORT,
        database=database,
    )
    # The session time zone decides how Postgres renders timestamps, and the
    # client reads dates and times straight out of those strings, so pin it to
    # the app's zone rather than whatever the database server defaults to.
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": f"-c timezone={env.TIMEZONE}"},
    )

engine = make_engine(env.DATABASE_NAME)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
