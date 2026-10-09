import time

from ..config import env
from ..database import SessionLocal, open_chat_db
from ..services.transaction_services import get_ingest_cursor
from .ingest import fetch_messages, ingest_rows

POLL_SECONDS = 5


def poll_once(db, chat_conn, cursor: int) -> int:
    """Ingest messages newer than cursor and return the new cursor.

    The cursor advances past messages that were skipped (non-transactions,
    filtered duplicates), so they are not re-read on every tick.
    """
    rows = fetch_messages(chat_conn, env.RBC_HANDLE_ID, cursor)
    if not rows:
        return cursor
    inserted = ingest_rows(db, rows)
    print(f"Read {len(rows)} new messages, stored {inserted} transactions.")
    return rows[-1][0]


def main():
    db = SessionLocal()
    chat_conn = open_chat_db()
    cursor = get_ingest_cursor(db)

    while True:
        try:
            cursor = poll_once(db, chat_conn, cursor)
        except Exception as exc:
            # Cursor is unchanged, so the same rows are retried next tick.
            db.rollback()
            print(f"Poll failed, will retry: {exc!r}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
