from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import get_db
from app.main import app
from app.services import clock
from app.services.insights import compute_digest, history, spending_summary, store_digest
from app.services.spending import spend_value

DAY = date(2026, 7, 10)  # a Friday


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def client(Session, monkeypatch):
    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(clock, "today", lambda now=None: DAY)
    yield TestClient(app)
    app.dependency_overrides.clear()


_next_id = iter(range(1, 10_000))


def add(db, when, amount, place="X", kind="CC Purchase"):
    db.add(models.Transaction(transaction_id=next(_next_id), transaction_datetime=when, amount=Decimal(amount),
                              place=place, transaction_type=kind))
    db.commit()


def at(day, hour=12, minute=0):
    return datetime(2026, 7, day, hour, minute)


@pytest.fixture()
def week(Session):
    """Hand-checkable July: see the expected numbers in the tests below."""
    db = Session()
    add(db, at(1), "15.00", "BOOKS")
    add(db, at(3), "10.00", "A")
    add(db, at(5), "20.00", "B")
    add(db, at(8), "1000.00", "", "Deposit")              # money in: not spending
    add(db, at(9), "200.00", "", "Credit Card Payment")   # money moving: not spending
    add(db, at(9), "30.00", "C")
    add(db, at(9), "5.00", "C", "Credit Refund")          # subtracts: Jul 9 nets 25
    add(db, at(10, 9), "6.00", "CAFE")
    add(db, at(10, 10), "4.00", "CAFE")
    add(db, at(10, 18), "50.00", "STORE")
    add(db, at(10, 19), "10.00", "STORE", "Credit Refund")
    return db


def test_spend_value_rules():
    assert spend_value("CC Purchase", "12.50") == Decimal("12.50")
    assert spend_value("Withdrawal", "20") == Decimal("20")
    assert spend_value("Credit Refund", "5") == Decimal("-5")
    assert spend_value("Deposit", "999") == 0
    assert spend_value("Credit Card Payment", "999") == 0
    assert spend_value("debit", None) == 0


def test_digest_math(week):
    d = compute_digest(week, DAY, final=True)
    assert Decimal(d["spend"]) == Decimal("50.00")                  # 6 + 4 + 50 - 10
    assert Decimal(d["avg_previous_7"]) == Decimal("7.86")          # (10 + 20 + 25) / 7
    assert d["pct_vs_avg"] == 536.4
    assert Decimal(d["month_to_date"]) == Decimal("120.00")         # 15 + 55 + 50
    assert Decimal(d["projected_month_end"]) == Decimal("372.00")   # 120 / 10 days * 31
    assert d["purchase_count"] == 3
    assert [(m["name"], m["total"], m["count"]) for m in d["top_merchants"]] == [
        ("STORE", "50.00", 1), ("CAFE", "10.00", 2)]


def test_no_percentage_without_a_baseline(Session):
    db = Session()
    add(db, at(10), "9.00")
    d = compute_digest(db, DAY)
    assert d["pct_vs_avg"] is None and Decimal(d["spend"]) == Decimal("9.00")


def test_empty_day_is_all_zeros(Session):
    d = compute_digest(Session(), DAY)
    assert Decimal(d["spend"]) == 0 and d["top_merchants"] == [] and d["unusual"] == []


def test_late_evening_purchase_counts_on_its_own_day(Session):
    db = Session()
    add(db, at(4, 23, 30), "12.00")  # 11:30pm Toronto, stored as local wall-clock time
    assert Decimal(compute_digest(db, date(2026, 7, 4))["spend"]) == Decimal("12.00")
    assert Decimal(compute_digest(db, date(2026, 7, 5))["spend"]) == 0


def test_day_boundaries_use_the_app_timezone_not_the_server_clock():
    just_after_midnight_utc = datetime(2026, 7, 5, 3, 30, tzinfo=timezone.utc)  # 11:30pm Jul 4 in Toronto
    assert clock.today(just_after_midnight_utc) == date(2026, 7, 4)
    assert clock.local_date(just_after_midnight_utc) == date(2026, 7, 4)
    assert clock.local_date(datetime(2026, 7, 5, 3, 30)) == date(2026, 7, 5)  # naive = already local


def test_recomputing_replaces_instead_of_duplicating(week):
    first = store_digest(week, DAY).model_dump(exclude={"computed_at"})
    second = store_digest(week, DAY).model_dump(exclude={"computed_at"})
    assert first == second
    assert week.query(models.DailyDigest).count() == 1


def test_unusual_charges(Session):
    db = Session()
    for day in (1, 2, 3, 4):
        add(db, at(day), "5.00", "COFFEE")
    add(db, at(10, 8), "30.00", "COFFEE")   # 6x the usual and $25 more
    add(db, at(10, 9), "7.00", "COFFEE")    # above usual but not twice it
    add(db, at(10, 12), "150.00", "NEWPLACE")  # big charge at a merchant with no history
    add(db, at(10, 13), "60.00", "OTHER")   # new merchant but under the $100 floor
    found = compute_digest(db, DAY)["unusual"]
    assert [(u["place"], u["amount"]) for u in found] == [("NEWPLACE", "150.00"), ("COFFEE", "30.00")]
    assert found[1]["reason"] == "6.0x your usual $5.00 at COFFEE"


def test_summary_counts_refunds_and_a_seven_day_rolling_window(week):
    s = spending_summary(week, DAY)
    assert s.daily == Decimal("50.00")
    assert s.weekly == Decimal("75.00")    # Mon Jul 6 .. Fri Jul 10: 25 + 50
    assert s.rolling == Decimal("95.00")   # Jul 4 .. Jul 10: 20 + 25 + 50 (Jul 3 is outside)
    assert s.monthly == Decimal("120.00")


def test_today_endpoint(client, week):
    body = client.get("/insights/today").json()
    assert body["day"] == "2026-07-10"
    assert Decimal(body["spend"]) == Decimal("50.00")
    assert body["top_merchants"][0]["name"] == "STORE"
    assert body["final"] is False   # the day is still in progress
    assert Decimal(body["projected_month_end"]) == Decimal("241.11")  # 9 completed days: 70 / 9 * 31


def test_history_endpoint_fills_in_days_and_skips_days_before_the_first_transaction(client, week, Session):
    body = client.get("/insights/history", params={"days": 30}).json()
    assert [d["day"] for d in body] == [f"2026-07-{n:02d}" for n in range(10, 0, -1)]
    assert Decimal(body[0]["spend"]) == Decimal("50.00")
    assert Decimal(body[1]["spend"]) == Decimal("25.00")
    stored = Session().query(models.DailyDigest).count()
    assert stored == 10
    assert client.get("/insights/history", params={"days": 3}).json()[2]["day"] == "2026-07-08"


def test_history_validates_days(client):
    assert client.get("/insights/history", params={"days": 0}).status_code == 422
    assert client.get("/insights/history", params={"days": 400}).status_code == 422


def test_history_is_empty_without_transactions(client):
    assert client.get("/insights/history").json() == []


def test_projection_needs_three_completed_days(Session):
    db = Session()
    add(db, date_at(1), "300.00", "RENT")
    first_of_month = compute_digest(db, date(2026, 7, 1), final=False)
    assert first_of_month["projected_month_end"] is None            # a lone day is not a pace
    assert compute_digest(db, date(2026, 7, 2), final=False)["projected_month_end"] is None
    assert Decimal(compute_digest(db, date(2026, 7, 3), final=True)["projected_month_end"]) == Decimal("3100.00")


def date_at(day):
    return datetime(2026, 7, day, 12, 0)


def test_refund_only_day(Session):
    db = Session()
    add(db, at(10), "12.00", "STORE", "Credit Refund")
    d = compute_digest(db, DAY, final=True)
    assert Decimal(d["spend"]) == Decimal("-12.00")
    assert d["purchase_count"] == 0 and d["top_merchants"] == []


def test_a_digest_stored_mid_day_is_recomputed_once_the_day_is_over(Session):
    db = Session()
    add(db, at(10, 9), "20.00", "A")
    during = history(db, DAY, 1)[0]                      # computed while July 10 is still "today"
    assert during.final is False and during.spend == Decimal("20.00")

    add(db, at(10, 22), "5.00", "B")                    # a late text for July 10
    next_day = date(2026, 7, 11)
    after = history(db, next_day, 2)
    assert [d.day for d in after] == [next_day, DAY]
    assert after[1].final is True and after[1].spend == Decimal("25.00")

    add(db, at(10, 23), "1.00", "C")                    # a final digest is served as stored
    assert history(db, next_day, 2)[1].spend == Decimal("25.00")


def test_outdated_stored_digest_is_recomputed_instead_of_crashing(Session):
    db = Session()
    add(db, at(8), "7.00", "A")
    add(db, at(9), "20.00", "A")
    # a row written by an older version of the code: wrong shape, claims to be final
    db.add(models.DailyDigest(day=date(2026, 7, 9), computed_at=datetime(2026, 7, 10),
                              payload={"day": "2026-07-09", "final": True}))
    db.commit()
    result = history(db, DAY, 3)
    assert [d.day for d in result] == [DAY, date(2026, 7, 9), date(2026, 7, 8)]
    assert result[1].spend == Decimal("20.00") and result[1].final is True


def test_cold_history_uses_a_fixed_number_of_queries(Session):
    db = Session()
    add(db, datetime(2026, 5, 1, 12), "9.00", "A")
    for day in range(1, 11):
        add(db, at(day), "10.00", "A")
    statements = []
    event.listen(Session.kw["bind"], "before_cursor_execute", lambda *a: statements.append(a[2]))
    assert len(history(db, DAY, 60)) == 60
    assert len(statements) <= 8   # first-transaction lookup, stored rows, one shared read, saves


def test_a_lost_race_on_the_first_save_is_retried(Session, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    db = Session()
    add(db, at(10), "20.00", "A")
    real_commit, calls = db.commit, []

    def flaky_commit():
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key"))
        real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    assert store_digest(db, DAY).spend == Decimal("20.00")
    assert len(calls) == 2


def test_unknown_timezone_is_rejected_at_startup():
    from pydantic import ValidationError
    from app.config import Env

    with pytest.raises(ValidationError):
        Env(TIMEZONE="Mars/Olympus_Mons")


def test_ingest_stamps_messages_with_the_app_timezone_not_the_machine_timezone(Session):
    from app.scripts.ingest import ingest_rows

    db = Session()
    # 2026-07-05 03:30 UTC is 11:30pm on July 4 in Toronto, whatever zone this machine is in.
    body = b"RBC: Purchase of $8.00 CAD made 07/04 at Late Night. STOP-TXT STOP/HELP-TXT HELP"
    assert ingest_rows(db, [(1, 1783222200, body)]) == 1
    stored = db.get(models.Transaction, 1).transaction_datetime
    assert (stored.year, stored.month, stored.day, stored.hour, stored.minute) == (2026, 7, 4, 23, 30)


def test_a_day_settles_two_hours_after_it_ends():
    utc = timezone.utc
    day = date(2026, 7, 10)  # ends at 04:00 UTC on Jul 11 in Toronto (EDT)
    assert clock.settled(day, datetime(2026, 7, 11, 5, 59, tzinfo=utc)) is False
    assert clock.settled(day, datetime(2026, 7, 11, 6, 0, tzinfo=utc)) is True


def test_a_digest_is_not_cached_until_the_day_has_settled(Session, monkeypatch):
    monkeypatch.setattr(clock, "settled", lambda day, now=None: False)
    db = Session()
    add(db, at(9, 12), "10.00", "A")
    assert history(db, DAY, 1)[0].spend == Decimal("0.00")
    add(db, at(10, 1), "4.00", "B")
    assert history(db, DAY, 1)[0].spend == Decimal("4.00")   # recomputed, not served from the table
    monkeypatch.undo()
    assert history(db, date(2026, 7, 11), 2)[1].spend == Decimal("4.00")   # settled: cached from here on
    add(db, at(10, 2), "1.00", "C")
    assert history(db, date(2026, 7, 11), 2)[1].spend == Decimal("4.00")
