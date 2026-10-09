"""
Run the real API against an in-memory SQLite database filled with made-up
spending, for trying the client without Postgres or any real data:

    python -m app.scripts.demo_server          # http://127.0.0.1:8000

DEMO DATA ONLY: every figure is invented. Nothing is read from or written to
Postgres, and the server refuses to start if it could be pointed at one.
"""

import os
import random
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

# The app reads database settings at import. Set placeholders unconditionally:
# real environment variables beat .env files, so this also overrides any real
# settings in the shell or in .env, and the demo can never reach a real database.
for key, value in {"DATABASE_HOSTNAME": "unused", "DATABASE_PORT": "5432", "DATABASE_USERNAME": "unused",
                   "DATABASE_PASSWORD": "unused", "DATABASE_NAME": "unused", "IP_ADDRESS": ""}.items():
    os.environ[key] = value

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .. import database, models
from ..database import get_db
from ..main import app
from ..services import clock

DAYS = 75
MERCHANTS = [("COFFEE LUNAR", 4, 7), ("GROCERY MART", 25, 110), ("CORNER DELI", 8, 18),
             ("TRANSIT CARD", 20, 20), ("BOOKSHOP", 12, 40), ("PIZZA PLACE", 15, 35), ("GAS STOP", 40, 70)]


def seed(db) -> None:
    rng = random.Random(42)
    today = clock.today()
    next_id = iter(range(1, 100_000))

    def add(day, hour, amount, place, kind="CC Purchase"):
        db.add(models.Transaction(
            transaction_id=next(next_id),
            transaction_datetime=datetime(day.year, day.month, day.day, hour, rng.randrange(60)),
            amount=Decimal(f"{amount:.2f}"), place=place, transaction_type=kind))

    for offset in range(DAYS, -1, -1):
        day = today - timedelta(days=offset)
        for _ in range(rng.choice([0, 1, 1, 2, 2, 3, 4])):
            place, low, high = rng.choice(MERCHANTS)
            add(day, rng.randrange(8, 21), rng.uniform(low, high), place)
        if day.day in (1, 15):
            add(day, 9, 2400, "", "Deposit")
        if day.weekday() == 4:
            add(day, 10, 350, "", "Credit Card Payment")
        if rng.random() < 0.06:
            add(day, 15, rng.uniform(5, 30), "BOOKSHOP", "Credit Refund")
    add(today, 12, 48.00, "COFFEE LUNAR")      # ~8x the usual: shows up under "Worth a look"
    add(today, 13, 31.25, "GROCERY MART")
    db.commit()


@asynccontextmanager
async def no_lifespan(_app):
    yield


def main() -> None:
    assert database.engine.url.host == "unused", "demo_server must never use real database settings"
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        seed(db)

    # The single in-memory SQLite connection is not safe for concurrent use, and
    # the page fires several requests at once, so handle one request at a time.
    lock = threading.Lock()

    def demo_db():
        with lock:
            db = Session()
            try:
                yield db
            finally:
                db.close()

    database.SessionLocal = Session   # scripts that open sessions directly get the demo database too
    app.dependency_overrides[get_db] = demo_db
    print("DEMO DATA ONLY: all figures are made up. http://127.0.0.1:8000")
    app.router.lifespan_context = no_lifespan   # skip create_all on the (unused) Postgres engine
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
