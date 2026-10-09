"""
Shared chat.db -> Postgres ingestion used by backfill.py and poller.py.
"""

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from .. import schemas
from ..services.clock import app_tz
from ..sms_parser import parse_message
from ..services.transaction_services import filter_cc_payment_duplicates, insert_transaction

_MESSAGES_QUERY = (
    "SELECT m.ROWID, m.date / 1000000000 + 978307200, m.attributedBody "
    "FROM message AS m JOIN handle AS h ON h.ROWID = m.handle_id "
    "WHERE h.id = ? AND m.ROWID > ? "
    "ORDER BY m.ROWID ASC"
)


def fetch_messages(chat_conn, handle_id: str, after_rowid: int = 0) -> list[tuple]:
    return chat_conn.execute(_MESSAGES_QUERY, (str(handle_id), after_rowid)).fetchall()


def ingest_rows(db: Session, rows: list[tuple]) -> int:
    """Parse and store rows; safe to repeat. Returns the number of new transactions.

    A message that can never be stored (unparseable amount, out-of-range value)
    is logged and skipped so it can't block every message after it. Anything
    else, such as the database being down, propagates so the caller retries.
    """
    batch = []
    for rowid, unix_seconds, body in rows:
        parsed = parse_message(body)
        if parsed is None:
            continue
        # chat.db stores UTC; attach the app timezone explicitly so the stored
        # instant is right whatever timezone this Mac or the database is set to.
        sent_at = datetime.fromtimestamp(unix_seconds, tz=app_tz()) if unix_seconds is not None else None
        candidate = {"transaction_id": rowid, "transaction_datetime": sent_at, **parsed}
        try:
            schemas.Transaction(**candidate)
        except ValidationError as exc:
            print(f"Skipping message {rowid}: {exc.error_count()} validation error(s)")
            continue
        batch.append(candidate)

    inserted = 0
    for transaction in filter_cc_payment_duplicates(batch, db):
        try:
            if insert_transaction(db, schemas.Transaction(**transaction)) is not None:
                inserted += 1
        except DataError:
            db.rollback()
            print(f"Skipping message {transaction['transaction_id']}: value out of range")
    return inserted
