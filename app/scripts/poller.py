"""
Long-running push of new RBC texts to the hosted API (run on the Mac):

    python -m app.scripts.poller

See pusher.py for the settings it needs.
"""

from .pusher import poller_main

if __name__ == "__main__":
    poller_main()
