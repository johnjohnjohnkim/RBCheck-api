import base64
import sqlite3

import pytest

from agent.ingest_agent import RBC_SENDER, read_new_messages

APPLE_EPOCH = 978307200


def make_chat_db(path, messages):
    """A minimal chat.db: just the columns the agent reads."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
        conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, handle_id INTEGER, date INTEGER, attributedBody BLOB)")
        conn.executemany("INSERT INTO handle VALUES (?, ?)", [(1, RBC_SENDER), (2, "+15555550123")])
        conn.executemany("INSERT INTO message VALUES (?, ?, ?, ?)", messages)
    conn.close()
    return path

@pytest.fixture
def chat_db(tmp_path):
    def apple_ns(unix):
        return (unix - APPLE_EPOCH) * 1_000_000_000
    return make_chat_db(tmp_path / "chat.db", [
        (10, 1, apple_ns(1_791_000_000), b"RBC: one"),
        (11, 2, apple_ns(1_791_000_100), b"from a friend"),
        (12, 1, apple_ns(1_791_000_200), None),
        (13, 1, apple_ns(1_791_000_300), b"RBC: three"),
    ])


def test_reads_only_rbc_texts_after_the_cursor_oldest_first(chat_db):
    messages = read_new_messages(chat_db, after_rowid=10)
    assert [m["rowid"] for m in messages] == [12, 13]

def test_converts_dates_to_unix_seconds_and_bodies_to_base64(chat_db):
    first, second = read_new_messages(chat_db, after_rowid=0, limit=2)
    assert first == {"rowid": 10, "sent_at": 1_791_000_000, "body_b64": base64.b64encode(b"RBC: one").decode()}
    assert second["body_b64"] is None

def test_respects_the_batch_limit(chat_db):
    assert [m["rowid"] for m in read_new_messages(chat_db, after_rowid=0, limit=1)] == [10]

def test_opens_the_database_read_only(chat_db):
    read_new_messages(chat_db, after_rowid=0)
    uri = chat_db.resolve().as_uri() + "?mode=ro"
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(uri, uri=True).execute("DELETE FROM message")
