import sqlite3
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import get_db
from app.main import app
from app.scripts.ingest import fetch_messages, ingest_rows
from app.scripts.poller import poll_once
from app.services.transaction_services import (
    MANUAL_ID_FLOOR,
    build_datetime_range,
    get_ingest_cursor,
)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def client(Session):
    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)  # no `with`: skip lifespan, which targets Postgres
    app.dependency_overrides.clear()


def tx(id, when="2026-07-04T12:00:00", amount="10.00", kind="CC Purchase", place="X"):
    return {"transaction_id": id, "transaction_datetime": when, "amount": amount,
            "place": place, "transaction_type": kind}


def test_build_datetime_range_accepts_either_order():
    a, b = date(2026, 7, 1), date(2026, 7, 5)
    assert build_datetime_range(a, b) == build_datetime_range(b, a)
    day_max, day_min = build_datetime_range(a, b)
    assert day_min < day_max


def test_date_range_start_before_end_returns_rows(client):
    client.post("/transactions", json=tx(1, "2026-07-03T09:00:00"))
    client.post("/transactions", json=tx(2, "2026-07-10T09:00:00"))
    r = client.get("/transactions/date_range", params={"start_date": "2026-07-01", "end_date": "2026-07-05"})
    assert [t["transaction_id"] for t in r.json()] == [1]


def test_bad_dates_are_422_not_500(client):
    assert client.get("/transactions/date", params={"date_str": "nope"}).status_code == 422
    assert client.get("/transactions/date_range", params={"start_date": "07/01/2026"}).status_code == 422


def test_duplicate_post_is_409(client):
    assert client.post("/transactions", json=tx(1)).status_code == 201
    assert client.post("/transactions", json=tx(1)).status_code == 409


def test_manual_entry_without_id_gets_server_id_in_int4_range(client):
    body = tx(0)
    del body["transaction_id"]
    first = client.post("/transactions", json=body).json()["transaction_id"]
    second = client.post("/transactions", json=body).json()["transaction_id"]
    assert MANUAL_ID_FLOOR <= first < second < 2**31


def test_patch_is_partial_and_cannot_change_primary_key(client):
    client.post("/transactions", json=tx(1, place="OLD"))
    r = client.patch("/transactions/1", json={"place": "NEW", "transaction_id": 99, "date": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["transaction_id"] == 1 and body["place"] == "NEW"
    assert body["transaction_type"] == "CC Purchase"


def test_pagination_bounds(client):
    assert client.get("/transactions/", params={"offset": -1, "limit": 10}).status_code == 422
    assert client.get("/transactions/", params={"offset": 0, "limit": 100000}).status_code == 422
    assert client.get("/transactions/").status_code == 200


def test_manual_ids_do_not_move_the_ingest_cursor(Session):
    db = Session()
    db.add(models.Transaction(transaction_id=500, transaction_datetime=datetime(2026, 7, 1), amount=1,
                              place="", transaction_type="Deposit"))
    db.add(models.Transaction(transaction_id=MANUAL_ID_FLOOR + 5, transaction_datetime=datetime(2026, 7, 2),
                              amount=1, place="", transaction_type="Deposit"))
    db.commit()
    assert get_ingest_cursor(db) == 500


@pytest.fixture()
def chat_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, handle_id INTEGER, date INTEGER, attributedBody BLOB);
        INSERT INTO handle VALUES (1, '72272'), (2, '555');
    """)
    return conn


def add_message(conn, rowid, text, handle=1):
    conn.execute("INSERT INTO message VALUES (?, ?, ?, ?)", (rowid, handle, 7.7e17 + rowid * 1e9, text.encode()))


def test_poller_ingests_filters_and_is_idempotent(Session, chat_db):
    add_message(chat_db, 10, "RBC: Purchase of $1,500.00 CAD made 07/04 at Shop. STOP-TXT STOP/HELP-TXT HELP")
    add_message(chat_db, 11, "RBC: Credit card ************1234 is due 07/20. Min pymt: $25.00 CAD. STOP-TXT STOP/HELP-TXT HELP.")
    add_message(chat_db, 12, "RBC: Purchase of $9.00 CAD made 07/04 at Other. STOP-TXT STOP/HELP-TXT HELP", handle=2)
    db = Session()

    cursor = poll_once(db, chat_db, 0)
    assert cursor == 11  # advanced past the skipped due-notice
    assert [t.transaction_id for t in db.query(models.Transaction).all()] == [10]
    assert float(db.get(models.Transaction, 10).amount) == 1500.00

    assert poll_once(db, chat_db, cursor) == cursor  # nothing new, no re-reads

    rows = fetch_messages(chat_db, "72272")
    assert ingest_rows(db, rows) == 0  # re-running a backfill adds nothing


def test_poller_cursor_survives_empty_database(Session, chat_db):
    add_message(chat_db, 5, "Deposit of $20.00 to RBC Acct TESTER made 07/04. STOP-TXT STOP/HELP-TXT HELP")
    db = Session()
    assert get_ingest_cursor(db) == 0
    assert poll_once(db, chat_db, get_ingest_cursor(db)) == 5


def test_explicit_id_must_fit_int4(client):
    assert client.post("/transactions", json=tx(3_000_000_000)).status_code == 422
    assert client.post("/transactions", json=tx(0)).status_code == 422


def test_amount_too_large_is_422_not_500(client, Session):
    # SQLite does not enforce Numeric(10, 2); the router maps Postgres DataError to 422.
    from sqlalchemy.exc import DataError
    from unittest.mock import patch
    with patch("app.routers.transactions.insert_transaction", side_effect=DataError("x", {}, Exception())):
        assert client.post("/transactions", json=tx(5)).status_code == 422


def test_patch_missing_transaction_is_404(client):
    assert client.patch("/transactions/12345", json={"place": "X"}).status_code == 404


def test_manual_id_collision_is_retried(Session, monkeypatch):
    from app.schemas import TransactionCreate
    from app.services import transaction_services as svc

    db = Session()
    first = svc.insert_transaction(db, TransactionCreate(**{k: v for k, v in tx(0).items() if k != "transaction_id"}))
    ids = iter([first.transaction_id, first.transaction_id + 1])  # first guess collides
    monkeypatch.setattr(svc, "next_manual_id", lambda _db: next(ids))
    second = svc.insert_transaction(db, TransactionCreate(**{k: v for k, v in tx(0).items() if k != "transaction_id"}))
    assert second.transaction_id == first.transaction_id + 1


def test_merchant_search_treats_wildcards_literally(client):
    client.post("/transactions", json=tx(1, place="A_B"))
    client.post("/transactions", json=tx(2, place="AXB"))
    names = [t["place"] for t in client.get("/transactions/merchant", params={"merchant": "A_B"}).json()]
    assert names == ["A_B"]


def test_pagination_is_stable_with_identical_timestamps(client):
    for i in range(1, 6):
        client.post("/transactions", json=tx(i, "2026-07-04T12:00:00"))
    seen = []
    for offset in (0, 2, 4):
        seen += [t["transaction_id"] for t in client.get("/transactions/", params={"offset": offset, "limit": 2}).json()]
    assert sorted(seen) == [1, 2, 3, 4, 5]


def test_poison_message_is_skipped_and_does_not_block_later_ones(Session, chat_db):
    add_message(chat_db, 1, "RBC: Purchase of $1.2.3 CAD made 07/04 at Bad. STOP-TXT STOP/HELP-TXT HELP")
    add_message(chat_db, 2, "RBC: Purchase of $4.00 CAD made 07/04 at Good. STOP-TXT STOP/HELP-TXT HELP")
    db = Session()
    cursor = poll_once(db, chat_db, 0)
    assert cursor == 2
    assert [t.transaction_id for t in db.query(models.Transaction).all()] == [2]


def test_database_outage_propagates_so_the_cursor_does_not_advance(chat_db):
    from sqlalchemy.exc import OperationalError

    class DownDb:
        def get(self, *a, **k):
            raise OperationalError("connect", {}, Exception("db down"))

    add_message(chat_db, 1, "Deposit of $20.00 to RBC Acct TESTER made 07/04. STOP-TXT STOP/HELP-TXT HELP")
    with pytest.raises(OperationalError):
        poll_once(DownDb(), chat_db, 0)


def test_withdrawal_matching_a_card_payment_is_dropped(Session):
    from app.services.transaction_services import filter_cc_payment_duplicates

    batch = [
        {"transaction_id": 1, "transaction_datetime": "2026-07-04 10:00:00", "amount": "300.00",
         "place": "", "transaction_type": "Credit Card Payment"},
        {"transaction_id": 2, "transaction_datetime": "2026-07-04 10:00:20", "amount": "300.00",
         "place": "", "transaction_type": "Withdrawal"},
        {"transaction_id": 3, "transaction_datetime": "2026-07-04 10:00:20", "amount": "40.00",
         "place": "", "transaction_type": "Withdrawal"},
    ]
    assert [t["transaction_id"] for t in filter_cc_payment_duplicates(batch, Session())] == [1, 3]


def test_withdrawal_matching_a_stored_card_payment_is_dropped(Session):
    from app.services.transaction_services import filter_cc_payment_duplicates

    db = Session()
    db.add(models.Transaction(transaction_id=1, transaction_datetime=datetime(2026, 7, 4, 10, 0, 0), amount=300,
                              place="", transaction_type="Credit Card Payment"))
    db.commit()
    later = [{"transaction_id": 2, "transaction_datetime": "2026-07-04 10:00:30", "amount": "300.00",
              "place": "", "transaction_type": "Withdrawal"}]
    assert filter_cc_payment_duplicates(later, db) == []


def test_explicit_id_in_the_manual_range_is_rejected(client):
    assert client.post("/transactions", json=tx(1_500_000_000)).status_code == 422


def test_duplicate_explicit_id_returns_none_from_the_service(Session):
    from app.schemas import TransactionCreate
    from app.services.transaction_services import insert_transaction

    db = Session()
    assert insert_transaction(db, TransactionCreate(**tx(7))) is not None
    assert insert_transaction(db, TransactionCreate(**tx(7))) is None


def test_exhausted_manual_id_retries_are_409(client, monkeypatch):
    from app.services import transaction_services as svc

    client.post("/transactions", json=tx(1))
    client.post("/transactions", json={k: v for k, v in tx(0).items() if k != "transaction_id"})
    taken = svc.MANUAL_ID_FLOOR
    monkeypatch.setattr(svc, "next_manual_id", lambda _db: taken)  # always collides
    body = {k: v for k, v in tx(0).items() if k != "transaction_id"}
    assert client.post("/transactions", json=body).status_code == 409
