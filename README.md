# RBCheck

A FastAPI backend that turns RBC (Royal Bank of Canada) SMS transaction alerts into a structured, queryable spending ledger.

RBC sends a text for every purchase, withdrawal, deposit, and credit card payment. On macOS those texts land in the iMessage database (`chat.db`). RBCheck reads that SQLite database, parses each message's embedded text for the amount/merchant/transaction type, and writes the result into a Postgres table that a REST API exposes to the [RBCheck-client](../RBCheck-client) frontend.

## How it works

1. **Ingestion** (`app/scripts/poller.py` or `app/scripts/backfill.py`) reads new rows from the `message`/`handle` tables in `chat.db` for the RBC SMS sender.
2. **Parsing** (`app/sms_parser.py`) extracts the readable text from each message's `attributedBody` blob, then regexes out the dollar amount, merchant name, and transaction type (`Deposit`, `Withdrawal`, `CC Purchase`, `Credit Card Payment`, `Credit Refund`, or a balance-warning marker).
3. **Deduplication** (`app/services/transaction_services.py`) drops `Withdrawal` rows that are really the settlement side of a `Credit Card Payment` seen within 60 seconds, checking both the current batch and existing Postgres rows.
4. **Storage** — each parsed transaction is inserted into Postgres via the `POST /transactions` endpoint, using a single SQLAlchemy `Transaction` model (`app/models.py`).
5. **API** (`app/routers/transactions.py`) serves summaries and filtered transaction lists to the client.

## Tech stack

- **FastAPI** + **Uvicorn** — HTTP API and ASGI server
- **SQLAlchemy** + **psycopg** — Postgres ORM/driver for the transactions table
- **Pydantic / pydantic-settings** — request/response schemas and env-based config
- **sqlite3** (stdlib) — read-only access to the iMessage `chat.db`

See `requirements.txt` for exact pinned versions.

## Project structure

```
RBCheck/
├── app/
│   ├── main.py                       FastAPI app, CORS config, router registration
│   ├── config.py                     Env settings (pydantic-settings, reads .env)
│   ├── database.py                   Postgres engine/session + SQLite chat.db connection
│   ├── models.py                     SQLAlchemy Transaction model
│   ├── schemas.py                    Pydantic schemas (Transaction, UpdateTransaction, SpendingDisplay, Date)
│   ├── sms_parser.py                 Extracts transaction text + amount/merchant/type from iMessage bodies
│   ├── routers/
│   │   └── transactions.py           /transactions REST endpoints
│   ├── services/
│   │   └── transaction_services.py   Date-range helper + CC-payment/withdrawal de-duplication
│   └── scripts/
│       ├── backfill.py               One-time import of all historical RBC texts into Postgres
│       └── poller.py                 Polls chat.db every 5s and pushes new transactions
├── copy_chat_db.py                   Dev utility: copies handle/message tables out of chat.db for testing off macOS
├── rbcheck.dockerfile                Container build for the API
└── requirements.txt
```

## Prerequisites

- Python 3.11+ (the Docker image uses `python:3.11-slim`)
- A running Postgres instance
- macOS with iMessage forwarding set up for the RBC SMS shortcode (for live ingestion) — on other platforms, a copy of `chat.db`'s `handle`/`message` tables (see [Dev utility: `copy_chat_db.py`](#dev-utility-copy_chat_dbpy))

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
cp app/.env.example app/.env
```

Fill in `app/.env`:

| Variable | Description |
|---|---|
| `DATABASE_HOSTNAME` | Postgres host |
| `DATABASE_PORT` | Postgres port |
| `DATABASE_USERNAME` | Postgres role |
| `DATABASE_PASSWORD` | Postgres password |
| `DATABASE_NAME` | Database name |
| `IP_ADDRESS` | Optional. Overrides `DATABASE_HOSTNAME` as the Postgres host |
| `TIMEZONE` | Optional. Zone the bank texts are written in, default `America/Toronto`. Decides what "today" means and how Postgres reads stored times, independent of the server's own timezone |
| `RBC_HANDLE_ID` | Optional. iMessage handle of the RBC sender (default `72272`) |
| `RBC_CHATDB_PATH` | Optional. Path to `chat.db` (default `~/Library/Messages/chat.db`) |

## Upgrading an existing database (timezone)

The API now sets the Postgres session timezone to `TIMEZONE` (default `America/Toronto`), and ingestion stamps each new transaction with an explicit timezone, so new rows are right wherever the Mac or the server runs. Rows stored by the older ingestion were *naive* local times, which Postgres read in whatever its own timezone was at the time. Before running this version against an existing database, run `SHOW timezone;` in `psql`:

- It already shows your zone (e.g. `America/Toronto`): nothing to do.
- It shows `UTC` (typical for Docker): the old rows were stored as if local time were UTC and will now read hours off, some on the wrong day. Back up first, then run this **exactly once** (running it again shifts every row a second time), ideally inside a transaction (`BEGIN; ... COMMIT;`) so you can check a few rows before committing:
  `UPDATE transactions SET transaction_datetime = (transaction_datetime AT TIME ZONE 'UTC') AT TIME ZONE 'America/Toronto';`
- Anything else: work out which zone the old rows were interpreted in and substitute it for `'UTC'` above.

## Running

Start the API:

```bash
uvicorn app.main:app --reload
```

Run ingestion (requires the API/Postgres to be reachable, since both scripts call the `send_transaction` handler directly):

```bash
python -m app.scripts.backfill   # one-time import of full chat.db history
python -m app.scripts.poller     # long-running, polls every 5 seconds
```

### Demo server (no Postgres, no real data)

```bash
python -m app.scripts.demo_server   # http://127.0.0.1:8000
```

Runs the real API on an in-memory SQLite database seeded with made-up spending, so the [client](../RBCheck-client) can be tried without Postgres or any of your data. Everything resets when it stops.

### Dev utility: `copy_chat_db.py`

`app/database.py` connects to `~/Library/Messages/chat.db` on every platform except Windows, where it falls back to a local `transactions.db` file (since there's no real iMessage database to read). To populate `transactions.db` for local testing, run `copy_chat_db.py` on a Mac that has the real `chat.db`, then copy the resulting `transactions.db` file into the `RBCheck/` root on Windows.

### Docker

```bash
docker build -f rbcheck.dockerfile -t rbcheck .
docker run --env-file app/.env -p 8000:8000 rbcheck
```

The image contains only the API (`app/`). It does not include `chat.db`, so ingestion (`backfill`/`poller`) still runs on the Mac.

## API

All endpoints are under `/transactions` (see `app/routers/transactions.py` for full details):

| Method | Path | Description |
|---|---|---|
| GET | `/transactions/summary` | Daily/weekly/rolling-7-day/monthly totals (excludes deposits and credit card payments) |
| GET | `/transactions/` | Paginated list (`offset`, `limit`) |
| GET | `/transactions/date?date_str=MM/DD/YYYY` | Transactions on a given date (defaults to today) |
| GET | `/transactions/weekly` | Transactions since Monday |
| GET | `/transactions/past_7_days` | Rolling 7-day window |
| GET | `/transactions/month` | Transactions since the 1st of the month |
| GET | `/transactions/date_range?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Transactions in an arbitrary range |
| GET | `/transactions/merchant?merchant=` | Case-insensitive merchant search |
| GET | `/transactions/price_range?range_start=&range_end=` | Transactions within an amount range |
| GET | `/transactions/{id}` | Single transaction |
| GET | `/insights/today` | Today's digest (recomputed on each call): spend, change vs the previous 7-day average, top merchants, month-to-date and projected month-end, unusual charges |
| GET | `/insights/history?days=30` | Digests for recent days, newest first. Past days are computed once and stored in `daily_digests` |
| POST | `/transactions` | Create a transaction |
| PATCH | `/transactions/{id}` | Partially update a transaction |

Spending counts purchases and withdrawals, subtracts refunds, and ignores deposits and credit card payments (`app/services/spending.py`). "Rolling 7 days" is the last seven days including today.

To rebuild stored digests (for example after editing old transactions) run `python -m app.scripts.digest --days 30`; with no flag it just stores today's.

CORS is restricted to `gwanwoo.dev`, its subdomains, and `localhost`/`127.0.0.1` (see `app/main.py`).

## Tests

```bash
pip install pytest
python -m pytest
```

The tests use in-memory SQLite and never touch Postgres or your real `chat.db`.
