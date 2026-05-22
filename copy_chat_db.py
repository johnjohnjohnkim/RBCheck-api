"""
Copies the message and handle tables from ~/Library/Messages/chat.db
into transactions.db so it can be used on another operating system.
"""

import sqlite3
import os

src_path = os.path.expanduser("~/Library/Messages/chat.db")
dst_path = os.path.join(os.path.dirname(__file__), "transactions.db")

src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)

with dst:
    for table in ("handle", "message"):
        src_cursor = src.execute(f"SELECT * FROM {table}")
        rows = src_cursor.fetchall()

        cols = [desc[0] for desc in src_cursor.description]
        placeholders = ", ".join("?" * len(cols))
        col_names = ", ".join(cols)

        dst.execute(f"DROP TABLE IF EXISTS {table}")
        create_sql = src.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
        ).fetchone()[0]
        dst.execute(create_sql)
        dst.executemany(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", rows)

        print(f"Copied {len(rows)} rows from {table}")

src.close()
dst.close()
print("Done.")
