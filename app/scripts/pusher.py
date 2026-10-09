"""
Mac side of ingestion: read RBC texts from chat.db, parse them, and push them to
the hosted API over HTTPS. Runs on the MacBook; needs no database credentials.

Settings (environment variables or a .env file in the working directory):
    RBCHECK_API_URL        e.g. https://api.rbcheck.gwanwoo.dev (must be https, except localhost)
    RBCHECK_WRITE_TOKEN    the API's WRITE_TOKEN
    RBC_HANDLE_ID          iMessage handle of the RBC sender (default 72272)
    RBC_CHATDB_PATH        path to chat.db (default ~/Library/Messages/chat.db)
    TIMEZONE               zone the texts were received in (default America/Toronto)
    POLL_SECONDS           how often to check for new texts (default 5, minimum 1)

Deliberately imports nothing from app.config / app.database (which need the
server's settings), so it runs with only the values above.
"""

import os
import sqlite3
import sys
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..sms_parser import parse_message

BATCH_SIZE = 200
MAX_BACKOFF_SECONDS = 300

_MESSAGES_QUERY = (
    "SELECT m.ROWID, m.date / 1000000000 + 978307200, m.attributedBody "
    "FROM message AS m JOIN handle AS h ON h.ROWID = m.handle_id "
    "WHERE h.id = ? AND m.ROWID > ? "
    "ORDER BY m.ROWID ASC"
)


class PushSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    RBCHECK_API_URL: str
    RBCHECK_WRITE_TOKEN: str
    RBC_HANDLE_ID: str = "72272"
    RBC_CHATDB_PATH: str | None = None
    TIMEZONE: str = "America/Toronto"
    POLL_SECONDS: int = Field(default=5, ge=1)

    @field_validator("RBCHECK_WRITE_TOKEN")
    @classmethod
    def _clean_token(cls, value: str) -> str:
        # A stray newline or space from a hand-edited .env would break the HTTP header.
        return value.strip()

    @field_validator("RBCHECK_API_URL")
    @classmethod
    def _https_only(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme == "https" or (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")):
            return value.rstrip("/")
        raise ValueError("RBCHECK_API_URL must be https:// (http is only allowed for localhost), "
                         "or the write token would be sent in clear text")


def chat_db_path(settings: PushSettings) -> str:
    if settings.RBC_CHATDB_PATH:
        return settings.RBC_CHATDB_PATH
    if sys.platform == "win32":
        # For testing on Windows: a copy made by copy_chat_db.py
        return os.path.join(os.path.dirname(__file__), "..", "..", "transactions.db")
    return os.path.expanduser("~/Library/Messages/chat.db")


def fetch_messages(chat_conn, handle_id: str, after_rowid: int = 0) -> list[tuple]:
    return chat_conn.execute(_MESSAGES_QUERY, (str(handle_id), after_rowid)).fetchall()


def local_max_rowid(chat_conn, handle_id: str) -> int:
    row = chat_conn.execute("SELECT MAX(m.ROWID) FROM message AS m JOIN handle AS h ON h.ROWID = m.handle_id "
                            "WHERE h.id = ?", (str(handle_id),)).fetchone()
    return row[0] or 0


def parse_rows(rows: list[tuple], tz: ZoneInfo) -> list[dict]:
    """Messages that are transactions, as JSON-ready dicts. chat.db stores UTC;
    each time is sent with an explicit offset in `tz`, so the stored instant is
    right whatever timezone this Mac is set to. A message that cannot be parsed
    is logged and skipped so it can't block the ones behind it."""
    records = []
    for rowid, unix_seconds, body in rows:
        try:
            parsed = parse_message(body)
            if parsed is None or unix_seconds is None:
                continue
            sent_at = datetime.fromtimestamp(unix_seconds, tz=tz)
        except (ValueError, OverflowError, OSError, TypeError) as exc:
            print(f"Skipping message {rowid}: {exc.__class__.__name__}")
            continue
        records.append({"transaction_id": rowid, "transaction_datetime": sent_at.isoformat(), **parsed})
    return records


class ApiClient:
    """Thin wrapper over the two ingest endpoints. Failures raise."""

    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=30,
                                         headers={"Authorization": f"Bearer {token}"})

    def cursor(self) -> int:
        response = self.http.get("/ingest/cursor")
        response.raise_for_status()
        return int(response.json()["cursor"])

    def push(self, transactions: list[dict]) -> dict:
        response = self.http.post("/ingest/batch", json={"transactions": transactions})
        response.raise_for_status()
        return response.json()


def poll_once(api: ApiClient, chat_conn, handle_id: str, tz: ZoneInfo, cursor: int,
              batch_size: int = BATCH_SIZE) -> int:
    """Push everything newer than `cursor`, a chunk of messages at a time, and
    return the new cursor. The cursor only moves past a chunk once the server has
    accepted it, so a failure leaves it at the last accepted chunk; the rest is
    sent again later and the server ignores anything it already has. It also moves
    past messages that are not transactions, so they are not re-read every tick."""
    rows = fetch_messages(chat_conn, handle_id, cursor)
    sent = stored = rejected = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        records = parse_rows(chunk, tz)
        if records:
            result = api.push(records)
            sent += len(records)
            stored += result["stored"]
            for rejection in result["rejected"]:
                rejected += 1
                print(f"Server rejected message {rejection['transaction_id']}: {rejection['reason']}")
        cursor = chunk[-1][0]
    if rows:
        print(f"Read {len(rows)} messages, sent {sent}, stored {stored}, rejected {rejected}.")
    return cursor


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"the server answered {code} (check RBCHECK_WRITE_TOKEN)"
        if 300 <= code < 400:
            return f"the server answered {code}, a redirect (check RBCHECK_API_URL; redirects are not followed)"
        return f"the server answered {code}"
    if isinstance(exc, httpx.HTTPError):
        return f"cannot reach the server ({exc.__class__.__name__})"
    if isinstance(exc, sqlite3.Error):
        return f"cannot read chat.db ({exc}); is Full Disk Access granted?"
    return f"unexpected {exc.__class__.__name__}: {exc}"


def run_forever(api: ApiClient, chat_conn, handle_id: str, tz: ZoneInfo, poll_seconds: int,
                sleep=time.sleep, should_stop=lambda: False) -> None:
    """Poll until stopped. Any failure (server down or erroring, a bad response,
    chat.db unreadable) is logged and retried with a growing delay up to five
    minutes. After a failure the cursor is re-read from the server, which is the
    source of truth for what it has stored."""
    cursor = None
    delay = poll_seconds
    while not should_stop():
        try:
            if cursor is None:
                cursor = api.cursor()
                local_max = local_max_rowid(chat_conn, handle_id)
                if cursor > local_max:
                    print(f"WARNING: the server has messages up to id {cursor} but chat.db only goes to "
                          f"{local_max}. Was Messages reset or the Mac replaced? "
                          "New texts with lower ids will not be sent until their ids pass the server's.")
            cursor = poll_once(api, chat_conn, handle_id, tz, cursor)
            delay = poll_seconds
        except Exception as exc:   # keep the poller alive whatever goes wrong
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
            print(f"Problem: {_describe(exc)}; retrying in {delay}s.")
            cursor = None
        sleep(delay)


def _open_chat_db(settings: PushSettings) -> sqlite3.Connection:
    path = chat_db_path(settings)
    if not os.path.exists(path):
        sys.exit(f"chat.db not found at {path}. Set RBC_CHATDB_PATH, and run this on the Mac that receives the texts.")
    conn = sqlite3.connect(path)
    try:
        conn.execute("SELECT 1 FROM message LIMIT 1")
    except sqlite3.Error as exc:
        sys.exit(f"Cannot read {path} ({exc}). On macOS, grant your terminal Full Disk Access "
                 "(System Settings > Privacy & Security).")
    return conn


def _setup() -> tuple[PushSettings, ApiClient, sqlite3.Connection, ZoneInfo]:
    settings = PushSettings()
    api = ApiClient(settings.RBCHECK_API_URL, settings.RBCHECK_WRITE_TOKEN)
    return settings, api, _open_chat_db(settings), ZoneInfo(settings.TIMEZONE)


def poller_main() -> None:
    settings, api, chat_conn, tz = _setup()
    print(f"Pushing RBC texts to {settings.RBCHECK_API_URL} every {settings.POLL_SECONDS}s.")
    run_forever(api, chat_conn, settings.RBC_HANDLE_ID, tz, settings.POLL_SECONDS)


def backfill_main() -> None:
    """One-off import of the whole history. Safe to run again: the server skips what it has."""
    settings, api, chat_conn, tz = _setup()
    poll_once(api, chat_conn, settings.RBC_HANDLE_ID, tz, cursor=0)
