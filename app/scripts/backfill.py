"""
One-off import of every RBC text in chat.db into the hosted API (run on the Mac):

    python -m app.scripts.backfill

Safe to run again; the server skips what it already has. See pusher.py for the settings it needs.
"""

from .pusher import backfill_main

if __name__ == "__main__":
    backfill_main()
