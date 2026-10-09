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
| `RBC_HANDLE_ID` | Optional. iMessage handle of the RBC sender (default `72272`) |
| `RBC_CHATDB_PATH` | Optional. Path to `chat.db` (default `~/Library/Messages/chat.db`) |

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
| POST | `/transactions` | Create a transaction |
| PATCH | `/transactions/{id}` | Partially update a transaction |

CORS is restricted to `gwanwoo.dev`, its subdomains, and `localhost`/`127.0.0.1` (see `app/main.py`).

## Tests

```bash
pip install pytest
python -m pytest
```

The tests use in-memory SQLite and never touch Postgres or your real `chat.db`.
