import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import READ_TOKEN, WRITE_TOKEN, bearer

from app import models
from app.database import get_db
from app.main import app
from app.scripts.pusher import ApiClient, fetch_messages, parse_rows, poll_once, run_forever

TORONTO = ZoneInfo("America/Toronto")
HANDLE = "72272"
PURCHASE = "RBC: Purchase of ${amount} CAD made 07/04 at {place}. STOP-TXT STOP/HELP-TXT HELP"


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def server(Session):
    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app, headers=bearer(WRITE_TOKEN))
    app.dependency_overrides.clear()


@pytest.fixture()
def api(server):
    return ApiClient("http://testserver", WRITE_TOKEN, http=server)


@pytest.fixture()
def chat_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, handle_id INTEGER, date INTEGER, attributedBody BLOB);
        INSERT INTO handle VALUES (1, '72272'), (2, '555');
    """)
    return conn


def add_message(conn, rowid, text, handle=1, unix=None):
    unix = 1783222200 + rowid if unix is None else unix   # 2026-07-05 03:30 UTC plus a second per row
    conn.execute("INSERT INTO message VALUES (?, ?, ?, ?)",
                 (rowid, handle, (unix - 978307200) * 1_000_000_000, text.encode()))


def stored_ids(Session):
    return sorted(t.transaction_id for t in Session().query(models.Transaction).all())


class Flaky:
    """Stands in for httpx.Client: fails the first `failures` calls like a dead network, then works."""

    def __init__(self, real, failures):
        self.real, self.failures, self.calls = real, failures, 0

    def _gate(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ConnectError("server is down")

    def get(self, *a, **k):
        self._gate()
        return self.real.get(*a, **k)

    def post(self, *a, **k):
        self._gate()
        return self.real.post(*a, **k)


# ── parsing on the Mac ──────────────────────────────────────────────────────────

def test_parse_rows_stamps_the_app_timezone_not_the_machine_timezone():
    body = PURCHASE.format(amount="1,234.56", place="Late Night").encode()
    records = parse_rows([(1, 1783222200, body)], TORONTO)   # 03:30 UTC on Jul 5 = 11:30pm Jul 4 in Toronto
    assert records == [{"transaction_id": 1, "transaction_datetime": "2026-07-04T23:30:00-04:00",
                        "amount": "1234.56", "place": "LATE NIGHT", "transaction_type": "CC Purchase"}]


def test_parse_rows_skips_what_is_not_a_transaction():
    rows = [(1, 1783222200, b"hello"), (2, None, PURCHASE.format(amount="5", place="A").encode()),
            (3, 1783222200, b"RBC: Credit card ************1234 is due 07/20. Min pymt: $25.00 CAD. STOP-TXT")]
    assert parse_rows(rows, TORONTO) == []


def test_pusher_imports_without_any_server_settings():
    # Checks the modules themselves, not just the environment: if the pusher pulled in
    # app.config it would read the repo's .env, and this assertion would still catch it.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_", "READ_TOKEN", "WRITE_TOKEN"))}
    repo = Path(__file__).resolve().parent.parent
    code = ("import sys; sys.path.insert(0, '.'); "
            "import app.scripts.pusher, app.scripts.poller, app.scripts.backfill; "
            "assert 'app.config' not in sys.modules and 'app.database' not in sys.modules")
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ── pushing ─────────────────────────────────────────────────────────────────────

def test_poll_once_sends_new_messages_once_and_ignores_other_senders(Session, api, chat_db):
    add_message(chat_db, 10, PURCHASE.format(amount="1,500.00", place="Shop"))
    add_message(chat_db, 11, "RBC: Credit card ************1234 is due 07/20. Min pymt: $25.00 CAD. STOP-TXT")
    add_message(chat_db, 12, PURCHASE.format(amount="9.00", place="Other"), handle=2)

    cursor = poll_once(api, chat_db, HANDLE, TORONTO, 0)
    assert cursor == 11                       # moved past the due-notice too
    assert stored_ids(Session) == [10]
    row = Session().get(models.Transaction, 10)
    assert float(row.amount) == 1500.00
    assert (row.transaction_datetime.hour, row.transaction_datetime.minute) == (23, 30)

    assert poll_once(api, chat_db, HANDLE, TORONTO, cursor) == cursor   # nothing new, nothing sent


def test_backfill_can_be_run_twice(Session, api, chat_db):
    for rowid in (1, 2, 3):
        add_message(chat_db, rowid, PURCHASE.format(amount=f"{rowid}.00", place="Shop"))
    poll_once(api, chat_db, HANDLE, TORONTO, 0)
    poll_once(api, chat_db, HANDLE, TORONTO, 0)
    assert stored_ids(Session) == [1, 2, 3]


def test_large_history_goes_in_batches(Session, api, chat_db):
    for rowid in range(1, 451):
        add_message(chat_db, rowid, PURCHASE.format(amount="1.00", place="Shop"))
    poll_once(api, chat_db, HANDLE, TORONTO, 0, batch_size=200)
    assert len(stored_ids(Session)) == 450


def test_a_bad_message_is_rejected_alone_and_does_not_block_later_ones(Session, api, chat_db, capsys):
    add_message(chat_db, 1, PURCHASE.format(amount="1.2.3", place="Bad"))
    add_message(chat_db, 2, PURCHASE.format(amount="4.00", place="Good"))
    assert poll_once(api, chat_db, HANDLE, TORONTO, 0) == 2
    assert stored_ids(Session) == [2]
    assert "Server rejected message 1" in capsys.readouterr().out


# ── resuming and surviving outages ──────────────────────────────────────────────

def test_a_restarted_poller_resumes_from_the_server_cursor(Session, server, chat_db):
    add_message(chat_db, 10, PURCHASE.format(amount="1.00", place="A"))
    first = ApiClient("http://testserver", WRITE_TOKEN, http=server)
    run_forever(first, chat_db, HANDLE, TORONTO, 5, sleep=lambda s: None, should_stop=_after(1))
    assert stored_ids(Session) == [10]

    add_message(chat_db, 11, PURCHASE.format(amount="2.00", place="B"))
    pushed = []
    restarted = ApiClient("http://testserver", WRITE_TOKEN, http=server)
    real_push = restarted.push
    restarted.push = lambda records: pushed.append([r["transaction_id"] for r in records]) or real_push(records)
    run_forever(restarted, chat_db, HANDLE, TORONTO, 5, sleep=lambda s: None, should_stop=_after(2))
    assert pushed == [[11]]                   # message 10 was not sent again
    assert stored_ids(Session) == [10, 11]


def _after(n):
    state = {"left": n}

    def should_stop():
        if state["left"] <= 0:
            return True
        state["left"] -= 1
        return False

    return should_stop


def test_the_poller_survives_the_server_being_down_and_loses_nothing(Session, server, chat_db):
    add_message(chat_db, 10, PURCHASE.format(amount="1.00", place="A"))
    flaky = Flaky(server, failures=3)
    api = ApiClient("http://testserver", WRITE_TOKEN, http=flaky)
    sleeps = []
    run_forever(api, chat_db, HANDLE, TORONTO, 5, sleep=sleeps.append, should_stop=_after(5))
    assert stored_ids(Session) == [10]        # delivered once the server came back
    assert sleeps[:3] == [10, 20, 40]         # backing off while it was down
    assert sleeps[3] == 5                     # back to the normal pace afterwards


def test_backoff_is_capped(Session, server, chat_db):
    api = ApiClient("http://testserver", WRITE_TOKEN, http=Flaky(server, failures=99))
    sleeps = []
    run_forever(api, chat_db, HANDLE, TORONTO, 5, sleep=sleeps.append, should_stop=_after(12))
    assert max(sleeps) == 300


def test_a_wrong_token_is_reported_and_retried_not_fatal(Session, server, chat_db, capsys):
    add_message(chat_db, 10, PURCHASE.format(amount="1.00", place="A"))
    wrong = TestClient(app, headers=bearer("wrong-token-wrong-token-wrong"))
    run_forever(ApiClient("http://testserver", "x", http=wrong), chat_db, HANDLE, TORONTO, 5,
                sleep=lambda s: None, should_stop=_after(2))
    assert stored_ids(Session) == []
    assert "check RBCHECK_WRITE_TOKEN" in capsys.readouterr().out


def test_a_read_token_is_refused_for_ingest(Session, chat_db, capsys):
    reader = TestClient(app, headers=bearer(READ_TOKEN))
    app.dependency_overrides[get_db] = lambda: iter([Session()])
    try:
        run_forever(ApiClient("http://testserver", "x", http=reader), chat_db, HANDLE, TORONTO, 5,
                    sleep=lambda s: None, should_stop=_after(1))
    finally:
        app.dependency_overrides.clear()
    assert "403" in capsys.readouterr().out


def test_a_server_error_keeps_the_cursor_and_the_next_try_works(Session, chat_db):
    add_message(chat_db, 10, PURCHASE.format(amount="1.00", place="A"))
    calls = {"n": 0}

    def flaky_db():
        calls["n"] += 1
        if calls["n"] <= 2:                   # the cursor lookup and the first push hit a broken database
            raise OperationalError("select", {}, Exception("db down"))
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = flaky_db
    try:
        broken = TestClient(app, headers=bearer(WRITE_TOKEN), raise_server_exceptions=False)
        sleeps = []
        run_forever(ApiClient("http://testserver", "x", http=broken), chat_db, HANDLE, TORONTO, 5,
                    sleep=sleeps.append, should_stop=_after(4))
    finally:
        app.dependency_overrides.clear()
    assert stored_ids(Session) == [10]
    assert sleeps[:2] == [10, 20]


# ── the server's batch endpoint ─────────────────────────────────────────────────

def item(id, **over):
    base = {"transaction_id": id, "transaction_datetime": "2026-07-04T12:00:00-04:00", "amount": "10.00",
            "place": "X", "transaction_type": "CC Purchase"}
    return {**base, **over}


def test_batch_rejects_bad_records_individually(Session, server):
    batch = [item(1), "not a dict", item(2, amount="0"), item(3, amount="-5"), item(4, amount="1e9"),
             item(5, transaction_type="Balance Warning!"), item(1_500_000_000), item(0), {"transaction_id": 6},
             item(7, transaction_datetime="yesterday"), item(8)]
    result = server.post("/ingest/batch", json={"transactions": batch}).json()
    assert result["stored"] == 2
    assert stored_ids(Session) == [1, 8]
    assert len(result["rejected"]) == 9


def test_batch_size_is_limited(server):
    too_many = [item(i) for i in range(1, 502)]
    assert server.post("/ingest/batch", json={"transactions": too_many}).status_code == 422


def test_repeated_batches_add_nothing(Session, server):
    batch = {"transactions": [item(1), item(2)]}
    assert server.post("/ingest/batch", json=batch).json()["stored"] == 2
    assert server.post("/ingest/batch", json=batch).json()["stored"] == 0


def test_cursor_ignores_manual_entries(Session, server):
    server.post("/ingest/batch", json={"transactions": [item(40)]})
    server.post("/transactions", json={"transaction_datetime": "2026-07-04T12:00:00", "amount": "1.00",
                                       "place": "M", "transaction_type": "debit"})
    assert server.get("/ingest/cursor").json() == {"cursor": 40}


def test_a_withdrawal_that_arrived_first_is_removed_when_its_card_payment_arrives(Session, server):
    withdrawal = item(1, transaction_type="Withdrawal", amount="300.00", transaction_datetime="2026-07-04T10:00:20-04:00")
    payment = item(2, transaction_type="Credit Card Payment", amount="300.00", transaction_datetime="2026-07-04T10:00:00-04:00")
    unrelated = item(3, transaction_type="Withdrawal", amount="40.00", transaction_datetime="2026-07-04T10:00:10-04:00")
    assert server.post("/ingest/batch", json={"transactions": [withdrawal, unrelated]}).json()["stored"] == 2
    result = server.post("/ingest/batch", json={"transactions": [payment]}).json()
    assert result["stored"] == 1 and result["dropped_withdrawals"] == 1
    assert stored_ids(Session) == [2, 3]


def test_a_withdrawal_arriving_after_its_card_payment_is_not_stored(Session, server):
    payment = item(2, transaction_type="Credit Card Payment", amount="300.00", transaction_datetime="2026-07-04T10:00:00-04:00")
    withdrawal = item(1, transaction_type="Withdrawal", amount="300.00", transaction_datetime="2026-07-04T10:00:20-04:00")
    server.post("/ingest/batch", json={"transactions": [payment]})
    assert server.post("/ingest/batch", json={"transactions": [withdrawal]}).json()["stored"] == 0
    assert stored_ids(Session) == [2]
