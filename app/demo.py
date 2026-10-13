"""
The public demo: its database is rebuilt every hour as a scrambled copy of
the real one, so the demo looks lived-in without showing real spending.

- About a fifth of the transactions are left out.
- Every amount is scaled by one hidden factor, then jittered on its own.
- Times move by up to 30 hours either way, never into the future.
- Merchant names become stand-ins from MERCHANTS; a real name always gets
  the same stand-in, so repeat visits still look like repeat visits.
- Ids are renumbered.

Every choice is keyed on a secret (the ingest key), so the public code alone
can't undo it.
"""

import asyncio
import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Engine, delete, insert, select, text

from . import models

log = logging.getLogger("uvicorn.error")

KEEP = 0.8
OVERALL_SCALE = (0.75, 1.25)
ROW_SCALE = (0.6, 1.5)
MAX_SHIFT = timedelta(hours=30)
REFRESH_SECONDS = 3600

MERCHANTS = [
    "BEAN & LEAF COFFEE", "MAPLE STREET CAFE", "DAILY GRIND ESPRESSO", "SUNRISE BAKERY",
    "NORTHSIDE GROCERS", "FRESHWAY MARKET", "GREEN VALLEY FOODS", "HARVEST FARM STAND",
    "CITY PHARMACY", "WELLCARE DRUGS", "QUICKSTOP CONVENIENCE", "CORNER STORE 24",
    "PIZZA PALACE", "NOODLE HOUSE", "SUSHI GARDEN", "BURGER BARN", "TACO STAND",
    "THAI BASIL KITCHEN", "PHO CORNER", "SEOUL BBQ HOUSE", "HARBOUR DINER", "CURRY LEAF",
    "TRANSIT FARES", "CITY PARKING", "RIDESHARE TRIP", "FUEL PLUS",
    "BOOKWORM BOOKS", "TECH CORNER", "HOMEGOODS DEPOT", "THREADS APPAREL", "SNEAKER SPOT",
    "STARLIGHT CINEMAS", "STREAMFLIX", "TUNEBOX MUSIC", "CLOUDSAFE STORAGE",
    "IRONWORKS FITNESS", "PET PANTRY", "PETAL & STEM FLOWERS", "HARDWARE HUB", "GAME VAULT",
]


def _unit(secret: str, *parts) -> float:
    """A number in [0, 1) fixed by the secret and the parts, unguessable without the secret."""
    digest = hmac.new(secret.encode(), ":".join(map(str, parts)).encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _between(u: float, low: float, high: float) -> Decimal:
    return Decimal(f"{low + (high - low) * u:.4f}")


def scramble(rows: list[dict], secret: str, now: datetime) -> list[dict]:
    """Demo rows from real ones (dicts with the transactions columns), oldest first."""
    overall = _between(_unit(secret, "scale"), *OVERALL_SCALE)
    demo = []
    for row in rows:
        real_id = row["transaction_id"]
        if _unit(secret, "keep", real_id) >= KEEP:
            continue

        amount = row["amount"]
        if amount is not None:
            scaled = Decimal(amount) * overall * _between(_unit(secret, "amount", real_id), *ROW_SCALE)
            amount = max(scaled.quantize(Decimal("0.01"), ROUND_HALF_UP), Decimal("0.01"))

        when = row["transaction_datetime"] + MAX_SHIFT * (2 * _unit(secret, "time", real_id) - 1)
        if when > now:
            when = min(row["transaction_datetime"], now)

        place = row["place"]
        if place:
            place = MERCHANTS[int(_unit(secret, "place", place.strip().upper()) * len(MERCHANTS))]

        demo.append({"transaction_datetime": when, "amount": amount, "place": place,
                     "transaction_type": row["transaction_type"]})

    demo.sort(key=lambda r: r["transaction_datetime"])
    for new_id, row in enumerate(demo, start=1):
        row["transaction_id"] = new_id
    return demo


def ensure_database(source: Engine, name: str) -> None:
    """Creates the demo database next to the real one if it isn't there yet."""
    if not re.fullmatch(r"\w+", name):
        raise ValueError(f"unexpected database name {name!r}")
    with source.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}).scalar():
            conn.execute(text(f'CREATE DATABASE "{name}"'))


def refresh(source: Engine, target: Engine, secret: str, now: datetime | None = None) -> int:
    """Replaces everything in the demo database with a fresh scramble of the real one."""
    if source.url.database == target.url.database:
        raise ValueError("the demo database must not be the real one")
    now = now or datetime.now(timezone.utc)
    transactions = models.Transaction.__table__
    with source.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(transactions))]
    demo = scramble(rows, secret, now)
    # One transaction: visitors see the old data or the new, never half of each.
    with target.begin() as conn:
        conn.execute(delete(models.DailyDigest.__table__))
        conn.execute(delete(transactions))
        if demo:
            conn.execute(insert(transactions), demo)
    return len(demo)


async def keep_fresh(source: Engine, target: Engine, secret: str) -> None:
    """Rebuilds the demo data now and then every hour, which also undoes visitors' edits."""
    while True:
        try:
            count = await asyncio.to_thread(refresh, source, target, secret)
            log.info("Demo data rebuilt: %d transactions", count)
        except Exception:
            log.exception("Demo data refresh failed; keeping the current data")
        await asyncio.sleep(REFRESH_SECONDS)
