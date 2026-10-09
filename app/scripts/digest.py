"""
Compute and store daily digests. Run once a day (cron / scheduled task).
The default of 2 days settles yesterday as well as today; use --days N to
rebuild more history, e.g. after editing old transactions:

    python -m app.scripts.digest --days 30
"""

import argparse
from datetime import timedelta

from ..database import SessionLocal
from ..services import clock
from ..services.insights import store_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=2, help="how many days back to (re)compute, today included; 2 also settles yesterday")
    args = parser.parse_args()

    db = SessionLocal()
    today = clock.today()
    try:
        for offset in range(max(args.days, 1)):
            store_digest(db, today - timedelta(days=offset))
    finally:
        db.close()
    print(f"Stored digests for the last {max(args.days, 1)} day(s) ending {today}.")


if __name__ == "__main__":
    main()
