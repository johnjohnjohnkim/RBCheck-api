"""
Forwards RBC texts from this Mac's Messages database to the RBCheck API.

Runs forever: every few seconds it reads texts newer than the last one it
sent and posts them to POST /ingest. The server parses and stores them, and
ignores any it already has, so resending after a crash or network drop is
safe. Uses only the standard library, so any python3 on the Mac will do.

    RBCHECK_API_URL=https://api.gwanwoo.dev RBCHECK_INGEST_KEY=... python3 ingest_agent.py

Reading ~/Library/Messages/chat.db needs Full Disk Access for the python
binary that runs this (System Settings → Privacy & Security).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

RBC_SENDER = "72272"  # The short code RBC texts from
POLL_SECONDS = 5
MAX_BACKOFF_SECONDS = 300
BATCH_SIZE = 500
HTTP_TIMEOUT_SECONDS = 30

# chat.db stores message.date as nanoseconds since 2001-01-01 UTC.
NEW_MESSAGES_SQL = """
    SELECT m.ROWID, m.date / 1000000000 + 978307200, m.attributedBody
    FROM message AS m
    JOIN handle AS h ON h.ROWID = m.handle_id
    WHERE h.id = ? AND m.ROWID > ?
    ORDER BY m.ROWID
    LIMIT ?
"""

log = logging.getLogger("rbcheck-agent")


def read_new_messages(chat_db: Path, after_rowid: int, limit: int = BATCH_SIZE) -> list[dict]:
    """Texts from RBC with a ROWID above `after_rowid`, oldest first, as /ingest payloads."""
    # Read-only, and a fresh connection each time so we never hold Messages' file open.
    uri = chat_db.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        rows = conn.execute(NEW_MESSAGES_SQL, (RBC_SENDER, after_rowid, limit)).fetchall()

    return [
        {
            "rowid": rowid,
            "sent_at": sent_at,
            "body_b64": base64.b64encode(body).decode() if body is not None else None,
        }
        for rowid, sent_at, body in rows
    ]


class Api:
    def __init__(self, base_url: str, ingest_key: str):
        self.base_url = base_url.rstrip("/")
        self.ingest_key = ingest_key

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-Ingest-Key": self.ingest_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)

    def last_rowid(self) -> int:
        return self._request("GET", "/ingest/cursor")["last_rowid"]

    def send(self, messages: list[dict]) -> dict:
        return self._request("POST", "/ingest", {"messages": messages})


def run(api: Api, chat_db: Path):
    # Ask the server where to start rather than keeping state on disk, so
    # the server is the one source of truth. Texts it dropped as duplicates
    # are below its cursor and get resent once per restart; it drops them again.
    cursor = None
    failures = 0
    while True:
        try:
            if cursor is None:
                cursor = api.last_rowid()
                log.info("Starting after ROWID %d", cursor)

            messages = read_new_messages(chat_db, cursor)
            if messages:
                result = api.send(messages)
                # Only move on once the server has the batch; a failure resends it.
                cursor = messages[-1]["rowid"]
                log.info("Sent %d texts, %d new, up to ROWID %d", result["received"], result["inserted"], cursor)

            failures = 0
            # A full batch means more are waiting (first run, or after downtime).
            delay = 0 if len(messages) == BATCH_SIZE else POLL_SECONDS
        except (OSError, sqlite3.Error, ValueError, KeyError) as error:
            # OSError covers network failures and HTTP errors (urllib's are subclasses).
            failures += 1
            delay = min(POLL_SECONDS * 2 ** failures, MAX_BACKOFF_SECONDS)
            detail = error.read().decode(errors="replace")[:500] if isinstance(error, urllib.error.HTTPError) else ""
            log.warning("Sync failed (%s %s), retrying in %ds", error, detail, delay)
        time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chat-db", type=Path, default=Path.home() / "Library/Messages/chat.db",
                        help="Messages database to read (default: %(default)s)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api_url = os.environ.get("RBCHECK_API_URL")
    ingest_key = os.environ.get("RBCHECK_INGEST_KEY")
    if not api_url or not ingest_key:
        parser.error("set RBCHECK_API_URL and RBCHECK_INGEST_KEY")

    run(Api(api_url, ingest_key), args.chat_db)


if __name__ == "__main__":
    main()
