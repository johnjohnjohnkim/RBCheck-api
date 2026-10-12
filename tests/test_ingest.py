import base64
from datetime import datetime, timezone
from decimal import Decimal

from app import models
from tests.conftest import INGEST_HEADERS


def message(rowid, sent_at, text):
    """An ingest payload for one text, wrapped the way chat.db's attributedBody wraps it."""
    blob = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84" + text.encode() + b"\x86\x84\x02iI"
    return {"rowid": rowid, "sent_at": sent_at, "body_b64": base64.b64encode(blob).decode()}

def purchase(rowid, sent_at, amount, place="TIM HORTONS"):
    return message(rowid, sent_at, f"RBC: A purchase of ${amount} was made at {place}. STOP-TXT to opt out. HELP-TXT HELP")

def withdrawal(rowid, sent_at, amount):
    return message(rowid, sent_at, f"RBC: A withdrawal of ${amount} was made. STOP-TXT to opt out. HELP-TXT HELP")

def cc_payment(rowid, sent_at, amount):
    return message(rowid, sent_at, f"RBC: A payment of ${amount} was made to your credit card. STOP-TXT to opt out. HELP-TXT HELP")

T0 = 1_791_000_000  # A fixed Unix time


def ingest(client, *messages):
    r = client.post("/ingest", json={"messages": list(messages)}, headers=INGEST_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()

def stored(db):
    return {t.transaction_id: t for t in db.query(models.Transaction).all()}


def test_rejects_missing_or_wrong_key(client):
    assert client.get("/ingest/cursor").status_code in (401, 403)
    assert client.get("/ingest/cursor", headers={"X-Ingest-Key": "nope"}).status_code == 401

def test_parses_and_stores_a_purchase(client, db):
    assert ingest(client, purchase(7, T0, "1,234.56")) == {"received": 1, "inserted": 1}

    t = stored(db)[7]
    assert t.amount == Decimal("1234.56")
    assert t.place == "TIM HORTONS"
    assert t.transaction_type == "CC Purchase"
    assert t.transaction_datetime == datetime.fromtimestamp(T0, timezone.utc)

def test_empty_body_is_stored_like_before(client, db):
    ingest(client, {"rowid": 3, "sent_at": T0, "body_b64": None})
    assert stored(db)[3].transaction_type == "Balance Warning!"

def test_sending_the_same_batch_twice_inserts_once(client, db):
    batch = [purchase(1, T0, "5.00"), purchase(2, T0 + 10, "6.00")]
    assert ingest(client, *batch)["inserted"] == 2
    assert ingest(client, *batch)["inserted"] == 0
    assert len(stored(db)) == 2

def test_cursor_is_the_highest_stored_rowid(client):
    assert client.get("/ingest/cursor", headers=INGEST_HEADERS).json() == {"last_rowid": 0}
    ingest(client, purchase(41, T0, "1.00"), purchase(40, T0, "1.00"))
    assert client.get("/ingest/cursor", headers=INGEST_HEADERS).json() == {"last_rowid": 41}

def test_withdrawal_matching_a_payment_in_the_same_batch_is_dropped(client, db):
    ingest(client, cc_payment(1, T0, "50.00"), withdrawal(2, T0 + 30, "50.00"))
    assert set(stored(db)) == {1}

def test_withdrawal_matching_an_earlier_stored_payment_is_dropped(client, db):
    ingest(client, cc_payment(1, T0, "50.00"))
    ingest(client, withdrawal(2, T0 + 30, "50.00"))
    assert set(stored(db)) == {1}

def test_unrelated_withdrawals_are_kept(client, db):
    ingest(client, cc_payment(1, T0, "50.00"), withdrawal(2, T0 + 30, "49.00"), withdrawal(3, T0 + 120, "50.00"))
    assert set(stored(db)) == {1, 2, 3}

def test_stored_withdrawal_is_removed_when_its_payment_arrives_later(client, db):
    ingest(client, withdrawal(1, T0, "50.00"), withdrawal(2, T0, "49.00"))
    ingest(client, cc_payment(3, T0 + 30, "50.00"))
    assert set(stored(db)) == {2, 3}
