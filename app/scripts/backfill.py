"""
A one-time use backfill python script to migrate a text message SQLite database <chat.db> to a detailed transaction postgres database.
Safe to re-run: transactions that already exist are skipped.
"""

from ..config import env
from ..database import SessionLocal, open_chat_db
from .ingest import fetch_messages, ingest_rows


def main():
    rows = fetch_messages(open_chat_db(), env.RBC_HANDLE_ID)
    db = SessionLocal()
    inserted = ingest_rows(db, rows)
    print(f"Read {len(rows)} messages, stored {inserted} new transactions.")


if __name__ == "__main__":
    main()
