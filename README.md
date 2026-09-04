# RBCheck

A personal transaction-tracking API. RBCheck reads the SMS transaction alerts
RBC (Royal Bank of Canada) sends to iMessage/SMS, parses them into structured
transactions, stores them in PostgreSQL, and serves them over a FastAPI HTTP
API for tracking spending.

## How it works

- RBC sends an SMS alert for every purchase, withdrawal, deposit, and credit
  card payment. On macOS these land in the Messages app and are stored in
  `~/Library/Messages/chat.db`.
- `app/sms_parser.py` extracts the amount, merchant, and transaction type out
  of the raw message body.
- `app/scripts/backfill.py` is a one-time script that reads all historical
  RBC messages out of `chat.db` and inserts them into Postgres.
- `app/scripts/poller.py` runs continuously (polling every 5 seconds),
  watching for new RBC messages and inserting them as they arrive.
- Both scripts run `app/services/transaction_services.py` first to drop
  `Withdrawal` entries that are really the same charge as a `Credit Card
  Payment` seen within 60 seconds, since RBC sends both for the same event.
- `app/main.py` exposes the resulting data through a FastAPI app
  (`app/routers/transactions.py`, `app/routers/users.py`).

## Platform requirements

Live ingestion (`poller.py`, `backfill.py`) requires **macOS**, since it reads
directly from `~/Library/Messages/chat.db`. The FastAPI app itself
(`app/main.py`) is plain Python and has no macOS dependency.

For development/testing on Windows, `app/database.py` falls back to a local
`transactions.db` file instead of `~/Library/Messages/chat.db`. Use
`copy_chat_db.py` (run on a machine with a real `chat.db`) to copy the
`handle` and `message` tables into that local `transactions.db` file.

## Requirements

- Python 3.11
- PostgreSQL

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the repository root (this is where `app/config.py`
loads it from) with the following variables. **Note:** `app/.env.example` is
currently out of date (it documents an older, removed version of this
project) — the variables below are the ones actually read by `app/config.py`
and `app/database.py`.

| Variable | Description |
|---|---|
| `DATABASE_USERNAME` | PostgreSQL role |
| `DATABASE_PASSWORD` | PostgreSQL password |
| `DATABASE_NAME` | Database name |
| `DATABASE_PORT` | PostgreSQL port (typically `5432`) |
| `IP_ADDRESS` | PostgreSQL host — this is the value actually used to build the connection string |
| `DATABASE_HOSTNAME` | Required by `app/config.py`, but currently **unused** in the actual database connection (see `IP_ADDRESS` above) |
| `SECRET_KEY` | Signing key for JWTs |
| `ALGORITHM` | JWT signing algorithm (e.g. `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT expiry, in minutes |

## Running the API

From the repository root:

```bash
uvicorn app.main:app --reload
```

On startup this creates any missing tables from `app/models.py` against the
configured Postgres database.

### Docker

```bash
docker build -f rbcheck.dockerfile -t rbcheck .
```

`rbcheck.dockerfile`'s `CMD` currently runs `uvicorn main:app`, which does not
match this project's package layout (`app/main.py` uses relative imports and
must be run as `app.main:app`). Until the Dockerfile is updated, run the
container with an overridden command, e.g.:

```bash
docker run --env-file .env -p 8000:8000 rbcheck uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Ingesting transactions

```bash
python -m app.scripts.backfill   # one-time: import all historical RBC messages
python -m app.scripts.poller     # continuous: watch for and insert new ones
```

## API

### Transactions (`/transactions`)

| Method & path | Description |
|---|---|
| `GET /transactions/summary` | Total spending for today, this week, the trailing 7 days, and this month (excludes `Credit Card Payment` and `Deposit`) |
| `GET /transactions/?offset=&limit=` | Paginated list, newest first |
| `GET /transactions/date?date_str=MM/DD/YYYY` | Transactions on a given day (defaults to today) |
| `GET /transactions/weekly` | Transactions since the start of this week (Monday) |
| `GET /transactions/past_7_days` | Transactions in the trailing 7 days |
| `GET /transactions/month` | Transactions this calendar month |
| `GET /transactions/date_range?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Transactions in a date range (`end_date` defaults to today) |
| `GET /transactions/merchant?merchant=` | Transactions where the merchant name contains the given substring |
| `GET /transactions/price_range?range_start=&range_end=` | Transactions within an amount range |
| `GET /transactions/{id}` | A single transaction by ID |
| `POST /transactions` | Create a transaction |
| `PATCH /transactions/{id}` | Update a transaction |

### Users (`/users`)

| Method & path | Description |
|---|---|
| `POST /users` | Create a user (signup) |

## Known issues

- **Auth is incomplete.** `app/oauth2.py` sets up JWT verification and
  expects a `/login` route (`OAuth2PasswordBearer(tokenUrl='login')`), but no
  such route exists yet — only `POST /users` (signup) is implemented.
  `oauth2.py` also queries `models.User`, but the actual model is
  `models.Users`, so `get_current_user` would fail if it were wired up to a
  route today.
- `rbcheck.dockerfile`'s `CMD` needs updating to match the current package
  layout (see [Docker](#docker) above).
