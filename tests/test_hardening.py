"""Regression tests for the milestone 4 review: poller resilience and the batch endpoint's edge cases."""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import WRITE_TOKEN, bearer
from test_pusher import (HANDLE, PURCHASE, TORONTO, Session, _after, add_message, api, chat_db,  # noqa: F401
                         item, server, stored_ids)

from app import models
from app.main import app
from app.scripts import pusher
from app.scripts.pusher import ApiClient, PushSettings, _open_chat_db, parse_rows, poll_once, run_forever


# ── poller resilience ───────────────────────────────────────────────────────────

def test_an_unparseable_message_is_skipped_and_does_not_block_the_rest(monkeypatch, capsys):
    real = pusher.parse_message

    def boom(body):
        if b"EXPLODE" in body:
            raise ValueError("malformed attributedBody")
        return real(body)

    monkeypatch.setattr(pusher, "parse_message", boom)
    rows = [(1, 1783222200, b"EXPLODE"), (2, 1783222200, PURCHASE.format(amount="3.00", place="Ok").encode())]
    assert [r["transaction_id"] for r in parse_rows(rows, TORONTO)] == [2]
    assert "Skipping message 1" in capsys.readouterr().out


def test_an_absurd_message_date_is_skipped(capsys):
    rows = [(1, 10**15, PURCHASE.format(amount="3.00", place="Far").encode())]
    assert parse_rows(rows, TORONTO) == []
    assert "Skipping message 1" in capsys.readouterr().out


class LockedChatDb:
    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")


def test_a_locked_chat_db_does_not_kill_the_poller(server, capsys):
    api = ApiClient("http://testserver", WRITE_TOKEN, http=server)
    sleeps = []
    run_forever(api, LockedChatDb(), HANDLE, TORONTO, 5, sleep=sleeps.append, should_stop=_after(3))
    assert sleeps == [10, 20, 40]
    assert "Full Disk Access" in capsys.readouterr().out


def test_a_non_json_reply_does_not_kill_the_poller(chat_db, capsys):
    add_message(chat_db, 10, PURCHASE.format(amount="1.00", place="A"))

    def html_page(request):
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(html_page))
    run_forever(ApiClient("http://x", "t", http=http), chat_db, HANDLE, TORONTO, 5,
                sleep=lambda s: None, should_stop=_after(2))
    assert "unexpected" in capsys.readouterr().out


def test_a_redirect_is_reported_with_a_hint(chat_db, capsys):
    def redirect(request):
        return httpx.Response(301, headers={"location": "https://elsewhere.example/"})

    http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(redirect))
    run_forever(ApiClient("http://x", "t", http=http), chat_db, HANDLE, TORONTO, 5,
                sleep=lambda s: None, should_stop=_after(1))
    assert "check RBCHECK_API_URL" in capsys.readouterr().out


def test_a_failure_part_way_through_a_big_import_keeps_what_was_accepted(Session, server, chat_db):
    for rowid in range(1, 7):
        add_message(chat_db, rowid, PURCHASE.format(amount=f"{rowid}.00", place="Shop"))
    calls = {"n": 0}
    real_post = server.post

    def post_failing_third(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise httpx.ConnectError("blip")
        return real_post(*args, **kwargs)

    flaky = type("Flaky", (), {"get": server.get, "post": staticmethod(post_failing_third)})()
    api = ApiClient("http://testserver", WRITE_TOKEN, http=flaky)
    with pytest.raises(httpx.ConnectError):
        poll_once(api, chat_db, HANDLE, TORONTO, 0, batch_size=2)
    assert stored_ids(Session) == [1, 2, 3, 4]            # two chunks were accepted
    assert api.cursor() == 4                              # the server cursor shows where to resume
    assert poll_once(api, chat_db, HANDLE, TORONTO, api.cursor(), batch_size=2) == 6
    assert stored_ids(Session) == [1, 2, 3, 4, 5, 6]


def test_a_chat_db_that_was_reset_is_flagged(server, chat_db, capsys):
    server.post("/ingest/batch", json={"transactions": [item(900)]})
    add_message(chat_db, 3, PURCHASE.format(amount="1.00", place="A"))
    api = ApiClient("http://testserver", WRITE_TOKEN, http=server)
    run_forever(api, chat_db, HANDLE, TORONTO, 5, sleep=lambda s: None, should_stop=_after(1))
    assert "WARNING" in capsys.readouterr().out


def test_settings_require_https_and_a_sane_interval():
    ok = dict(RBCHECK_WRITE_TOKEN="x", _env_file=None)
    assert PushSettings(RBCHECK_API_URL="https://api.example/", **ok).RBCHECK_API_URL == "https://api.example"
    assert PushSettings(RBCHECK_API_URL="http://127.0.0.1:8000", **ok)
    for bad in ("http://api.example", "ftp://api.example", "api.example"):
        with pytest.raises(ValidationError):
            PushSettings(RBCHECK_API_URL=bad, **ok)
    with pytest.raises(ValidationError):
        PushSettings(RBCHECK_API_URL="https://api.example", POLL_SECONDS=0, **ok)


def test_a_missing_chat_db_stops_with_a_clear_message(tmp_path):
    settings = PushSettings(RBCHECK_API_URL="https://api.example", RBCHECK_WRITE_TOKEN="x",
                            RBC_CHATDB_PATH=str(tmp_path / "nope.db"), _env_file=None)
    with pytest.raises(SystemExit, match="chat.db not found"):
        _open_chat_db(settings)
    assert not (tmp_path / "nope.db").exists()            # and no empty file was created


# ── the batch endpoint ──────────────────────────────────────────────────────────

def at(seconds, id, **over):
    return item(id, transaction_datetime=f"2026-07-04T10:00:{seconds:02d}-04:00", **over)


def test_two_real_withdrawals_beside_one_payment_keep_one(Session, server):
    batch = [at(0, 1, transaction_type="Credit Card Payment", amount="300.00"),
             at(0, 2, transaction_type="Withdrawal", amount="300.00"),
             at(30, 3, transaction_type="Withdrawal", amount="300.00")]
    server.post("/ingest/batch", json={"transactions": batch})
    assert stored_ids(Session) == [1, 3]                  # the payment absorbed exactly one withdrawal


def test_a_late_payment_removes_only_the_closest_stored_withdrawal(Session, server):
    server.post("/ingest/batch", json={"transactions": [
        at(0, 1, transaction_type="Withdrawal", amount="300.00"),
        at(30, 2, transaction_type="Withdrawal", amount="300.00")]})
    result = server.post("/ingest/batch", json={"transactions": [
        at(28, 3, transaction_type="Credit Card Payment", amount="300.00")]}).json()
    assert result["dropped_withdrawals"] == 1
    assert stored_ids(Session) == [1, 3]                  # id 2 was the closest and went


def test_a_payment_paired_inside_the_batch_does_not_also_remove_a_stored_withdrawal(Session, server):
    server.post("/ingest/batch", json={"transactions": [at(0, 5, transaction_type="Withdrawal", amount="300.00")]})
    server.post("/ingest/batch", json={"transactions": [
        at(20, 6, transaction_type="Withdrawal", amount="300.00"),
        at(10, 7, transaction_type="Credit Card Payment", amount="300.00")]})
    assert stored_ids(Session) == [5, 7]                  # id 6 paired with the payment; id 5 is a genuine withdrawal


def test_replaying_a_stored_payment_alone_cannot_delete_a_genuine_withdrawal(Session, server):
    server.post("/ingest/batch", json={"transactions": [
        at(0, 1, transaction_type="Credit Card Payment", amount="300.00"),
        at(0, 2, transaction_type="Withdrawal", amount="300.00"),    # absorbed by the payment
        at(30, 3, transaction_type="Withdrawal", amount="300.00")]}) # genuine: kept
    assert stored_ids(Session) == [1, 3]
    # A later batch repeats the payment (without its withdrawal) and adds an unrelated record.
    # The payment is already stored, so it must not delete id 3; and the unrelated record's
    # commit must not flush a deletion left pending by the skipped payment.
    server.post("/ingest/batch", json={"transactions": [
        at(0, 1, transaction_type="Credit Card Payment", amount="300.00"),
        at(50, 4, transaction_type="CC Purchase", amount="9.00")]})
    assert stored_ids(Session) == [1, 3, 4]


def test_a_whitespace_padded_write_token_is_cleaned():
    settings = PushSettings(RBCHECK_API_URL="https://api.example", RBCHECK_WRITE_TOKEN="  tok\n", _env_file=None)
    assert settings.RBCHECK_WRITE_TOKEN == "tok"


def test_replaying_a_batch_never_removes_a_second_genuine_withdrawal(Session, server):
    batch = {"transactions": [at(0, 1, transaction_type="Credit Card Payment", amount="300.00"),
                              at(0, 2, transaction_type="Withdrawal", amount="300.00"),
                              at(30, 3, transaction_type="Withdrawal", amount="300.00")]}
    server.post("/ingest/batch", json=batch)
    # What a poller restart does, with a new record after the replayed ones: if the
    # deletion pending for the already-stored payment leaked, that record's commit would flush it.
    replay = {"transactions": batch["transactions"] + [at(50, 4, transaction_type="CC Purchase", amount="9.00")]}
    for _ in range(3):
        server.post("/ingest/batch", json=replay)
    assert stored_ids(Session) == [1, 3, 4]


def test_manual_withdrawals_are_never_removed_by_a_card_payment(Session, server):
    server.post("/transactions", json={"transaction_datetime": "2026-07-04T10:00:10", "amount": "300.00",
                                       "place": "Cash", "transaction_type": "Withdrawal"})
    server.post("/ingest/batch", json={"transactions": [
        at(0, 1, transaction_type="Credit Card Payment", amount="300.00")]})
    kinds = sorted(t.transaction_type for t in Session().query(models.Transaction).all())
    assert kinds == ["Credit Card Payment", "Withdrawal"]


def test_a_crash_between_the_payment_and_the_clean_up_cannot_leave_a_double_count(Session, server, monkeypatch):
    from app.services import ingestion

    server.post("/ingest/batch", json={"transactions": [at(10, 1, transaction_type="Withdrawal", amount="300.00")]})
    payment = {"transactions": [at(0, 2, transaction_type="Credit Card Payment", amount="300.00")]}
    real_insert = ingestion.insert_transaction

    def die(db, transaction):
        raise RuntimeError("process died")

    monkeypatch.setattr(ingestion, "insert_transaction", die)
    broken = TestClient(app, headers=bearer(WRITE_TOKEN), raise_server_exceptions=False)
    assert broken.post("/ingest/batch", json=payment).status_code == 500
    assert stored_ids(Session) == [1]                     # neither the payment nor the deletion happened

    monkeypatch.setattr(ingestion, "insert_transaction", real_insert)
    server.post("/ingest/batch", json=payment)            # the retry completes both together
    assert stored_ids(Session) == [2]


def test_hostile_ids_and_times_are_rejected_not_500(Session, server):
    batch = [{"transaction_id": "abc"}, {"transaction_id": [1]}, {"transaction_id": {"a": 1}},
             item(1, transaction_datetime="0001-01-01T00:00:00Z"),
             item(2, transaction_datetime="9999-12-31T23:59:59Z"),
             item(3, transaction_datetime="1999-12-31T23:59:59Z"),
             item(4, transaction_datetime="2999-01-01T00:00:00Z"), None, 7, [], item(5)]
    response = server.post("/ingest/batch", json={"transactions": batch})
    assert response.status_code == 200
    body = response.json()
    assert body["stored"] == 1 and stored_ids(Session) == [5]
    assert all(r["transaction_id"] is None or isinstance(r["transaction_id"], int) for r in body["rejected"])


def test_oversized_bodies_are_refused_before_they_are_read(server):
    blob = "x" * 1_100_000
    assert server.post("/ingest/batch", json={"transactions": [{"place": blob}]}).status_code == 413
    assert TestClient(app).post("/ingest/batch", json={"transactions": [{"place": blob}]}).status_code == 413
