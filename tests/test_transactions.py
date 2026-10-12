from tests.conftest import INGEST_HEADERS
from tests.test_ingest import T0, purchase


def create(client, **overrides):
    body = {
        # What the client sends today, including a Date.now() id the server ignores.
        "transaction_id": 1_791_000_000_000, "amount": "4.50", "place": "CAFE",
        "transaction_datetime": "2026-10-12T12:00:00", "transaction_type": "debit",
    } | overrides
    r = client.post("/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_hand_entered_transactions_get_negative_ids(client):
    assert create(client)["transaction_id"] == -1
    assert create(client)["transaction_id"] == -2

def test_hand_entered_transactions_do_not_move_the_ingest_cursor(client):
    client.post("/ingest", json={"messages": [purchase(500, T0, "1.00")]}, headers=INGEST_HEADERS)
    create(client)
    assert client.get("/ingest/cursor", headers=INGEST_HEADERS).json() == {"last_rowid": 500}

def test_patch_ignores_the_id_and_date_the_client_sends(client):
    tx = create(client)
    r = client.patch(f"/transactions/{tx['transaction_id']}", json={
        "transaction_id": 999, "date": "10/12/2026", "amount": 7, "place": "DINER",
        "transaction_datetime": "2026-10-12T13:15:00", "transaction_type": "debit",
    })
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["transaction_id"] == tx["transaction_id"]
    assert updated["place"] == "DINER"
    assert updated["transaction_datetime"].startswith("2026-10-12T13:15:00")

def test_patch_of_a_missing_transaction_is_404(client):
    assert client.patch("/transactions/12345", json={"place": "X"}).status_code == 404

def test_health(anon_client):
    assert anon_client.get("/health").json() == {"status": "ok"}
