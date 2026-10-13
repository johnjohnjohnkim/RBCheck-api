from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app import models
from app.services import clock

TORONTO = ZoneInfo("America/Toronto")


def add(db, id, local_dt, amount="10.00", type="CC Purchase"):
    db.add(models.Transaction(
        transaction_id=id, transaction_datetime=local_dt.replace(tzinfo=TORONTO),
        amount=Decimal(amount), place="SHOP", transaction_type=type,
    ))
    db.commit()

def ids(response):
    assert response.status_code == 200, response.text
    return {t["transaction_id"] for t in response.json()}

@pytest.fixture
def today_is(monkeypatch):
    def set_today(d):
        monkeypatch.setattr(clock, "today", lambda now=None: d)
    return set_today


def test_day_range_spans_local_midnight_to_midnight():
    start, end = clock.day_range(date(2026, 10, 12))
    assert start == datetime(2026, 10, 12, tzinfo=TORONTO)
    assert end == datetime(2026, 10, 13, tzinfo=TORONTO)

def test_day_range_covers_the_daylight_saving_change():
    start, end = clock.day_range(date(2026, 11, 1))
    # Subtracting two times in the same zone compares wall clocks, so go through UTC.
    assert end.astimezone(timezone.utc) - start.astimezone(timezone.utc) == timedelta(hours=25)

def test_date_splits_at_local_midnight(client, db):
    add(db, 1, datetime(2026, 10, 12, 23, 30))
    add(db, 2, datetime(2026, 10, 13, 0, 10))
    assert ids(client.get("/transactions/date", params={"date_str": "10/12/2026"})) == {1}
    assert ids(client.get("/transactions/date", params={"date_str": "10/13/2026"})) == {2}

def test_date_rejects_a_malformed_date(client):
    assert client.get("/transactions/date", params={"date_str": "2026-10-12"}).status_code == 422

def test_times_come_back_in_local_time(client, db):
    add(db, 1, datetime(2026, 10, 12, 23, 30))
    tx = client.get("/transactions/1").json()
    assert tx["transaction_datetime"].startswith("2026-10-12T23:30:00")

def test_date_range_accepts_either_order(client, db):
    add(db, 1, datetime(2026, 10, 1, 9))
    add(db, 2, datetime(2026, 10, 5, 9))
    add(db, 3, datetime(2026, 10, 9, 9))
    params = {"start_date": "2026-10-01", "end_date": "2026-10-05"}
    assert ids(client.get("/transactions/date_range", params=params)) == {1, 2}
    params = {"start_date": "2026-10-05", "end_date": "2026-10-01"}
    assert ids(client.get("/transactions/date_range", params=params)) == {1, 2}

def test_week_month_and_rolling_windows(client, db, today_is):
    today_is(date(2026, 10, 14))  # A Wednesday
    add(db, 1, datetime(2026, 9, 30, 12))   # Last month
    add(db, 2, datetime(2026, 10, 7, 12))   # Exactly 7 days ago
    add(db, 3, datetime(2026, 10, 11, 23))  # Sunday, last week
    add(db, 4, datetime(2026, 10, 12, 0, 5))  # Monday, this week
    add(db, 5, datetime(2026, 10, 14, 23, 59))

    assert ids(client.get("/transactions/weekly")) == {4, 5}
    assert ids(client.get("/transactions/past_7_days")) == {2, 3, 4, 5}
    assert ids(client.get("/transactions/month")) == {2, 3, 4, 5}

def test_summary_uses_local_days_and_skips_payments_and_deposits(client, db, today_is):
    today_is(date(2026, 10, 14))
    add(db, 1, datetime(2026, 10, 13, 23, 59), "1.00")
    add(db, 2, datetime(2026, 10, 14, 0, 1), "2.00")
    add(db, 3, datetime(2026, 10, 14, 9), "100.00", "Deposit")
    add(db, 4, datetime(2026, 10, 14, 9), "100.00", "Credit Card Payment")

    summary = client.get("/transactions/summary").json()
    assert Decimal(summary["daily"]) == Decimal("2.00")
    assert Decimal(summary["weekly"]) == Decimal("3.00")

def test_wall_clock_times_from_the_client_are_read_as_local(client, db):
    r = client.post("/transactions", json={
        "transaction_id": 9, "amount": "4.50", "place": "CAFE",
        "transaction_datetime": "2026-10-12T23:30:00", "transaction_type": "debit",
    })
    assert r.status_code == 201, r.text
    assert ids(client.get("/transactions/date", params={"date_str": "10/12/2026"})) == {r.json()["transaction_id"]}
