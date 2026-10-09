# RBCheck

A FastAPI backend that turns RBC (Royal Bank of Canada) SMS transaction alerts into a spending ledger with daily insights, plus the Mac-side script that feeds it.

RBC sends a text for every purchase, withdrawal, deposit, and credit card payment. On macOS those texts land in the iMessage database (`chat.db`). A script on the Mac reads them, parses each one, and **pushes** the result over HTTPS to the API, which stores it in Postgres and serves it to the [RBCheck-client](../RBCheck-client) page.

```
iPhone SMS → iMessage → MacBook ──(parse, HTTPS + write token)──▶ API ──▶ Postgres
                                                                    ▲
                                              browser page ─(read token)┘
```

The API and Postgres can live anywhere (the plan is one small AWS instance running Docker). The Mac needs no database access, only the API's address and a token. If the Mac is off, the site still serves all history; the poller catches up when it comes back.

## How it works

1. **Parsing, on the Mac** (`app/sms_parser.py`, `app/scripts/pusher.py`). Each message's `attributedBody` is decoded, then the amount, merchant and type are extracted (`Deposit`, `Withdrawal`, `CC Purchase`, `Credit Card Payment`, `Credit Refund`). Messages that are not transactions (balance warnings, "card is due" notices) are skipped. Each time is sent with an explicit timezone offset, whatever timezone the Mac is in.
2. **Pushing** (`app/scripts/poller.py`, `backfill.py`). The poller asks the API for the last message id it has (`GET /ingest/cursor`), then sends anything newer in batches (`POST /ingest/batch`). The cursor only moves after the server accepts a batch. If the server is down it retries with a growing delay (up to 5 minutes) and loses nothing.
3. **Storing** (`app/services/ingestion.py`). Each record is validated on its own: a bad one is reported back and skipped, it never blocks the rest. Repeats are ignored. A `Withdrawal` that is really the settlement side of a `Credit Card Payment` (same amount within 60 seconds) is dropped whichever of the two arrives first. Pairing is one-to-one: a payment absorbs at most one withdrawal (the closest), so two genuine withdrawals of the same amount are not both lost, and a payment and the removal of its withdrawal are committed together. Manual entries are never removed.
4. **Insights** (`app/services/insights.py`). One digest per local day: spend, change vs the previous 7-day average, top merchants, month-to-date and month-end pace, unusual charges.
5. **API** (`app/routers/`). Summaries, lists and digests for the client, all behind bearer tokens.

## Tech stack

FastAPI + Uvicorn, SQLAlchemy + psycopg (Postgres), Pydantic / pydantic-settings, httpx (the Mac pusher), sqlite3 (reading `chat.db`). Exact versions in `requirements.txt`.

## Project structure

```
RBCheck/
├── app/
│   ├── main.py            App, CORS, routers, /healthz (docs are off unless ENABLE_DOCS=true)
│   ├── config.py          Server settings (reads .env) - tokens are required
│   ├── auth.py            Bearer-token checks (read / write)
│   ├── database.py        Postgres engine and session
│   ├── models.py          Transaction and DailyDigest tables
│   ├── schemas.py         Request/response models
│   ├── sms_parser.py      iMessage text -> amount / merchant / type
│   ├── routers/           transactions.py, insights.py, ingest.py
│   ├── services/          clock, spending rules, insights, ingestion, transaction helpers
│   └── scripts/
│       ├── pusher.py      Mac side: read chat.db, parse, push (needs no database settings)
│       ├── poller.py      python -m app.scripts.poller    (runs forever)
│       ├── backfill.py    python -m app.scripts.backfill  (one-off history import)
│       ├── digest.py      python -m app.scripts.digest    (store digests; for a daily cron)
│       └── demo_server.py Real API on made-up data, no Postgres
├── tests/                 pytest suite (SQLite; never touches Postgres or your messages)
├── copy_chat_db.py        Dev utility: copy handle/message tables out of chat.db
├── rbcheck.dockerfile     The API image (non-root, health-checked)
├── docker-compose.yml     The hosted stack: Postgres + API + digest job + Caddy (HTTPS)
├── Caddyfile              Reverse proxy: automatic HTTPS, 1 MB body limit
├── deploy.env.example     Settings for the stack (copy to deploy.env)
├── docs/MIGRATING-DATA.md Moving your existing data into the hosted database
└── requirements.txt
```

## Setup: the server (API + Postgres)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
cp app/.env.example .env     # then fill it in; see app/.env.example for every variable
```

Required: the `DATABASE_*` settings and two tokens, `READ_TOKEN` and `WRITE_TOKEN` (each at least 24 characters, and different). The app refuses to start without them. Generate each with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Variable | Description |
|---|---|
| `DATABASE_HOSTNAME`, `DATABASE_PORT`, `DATABASE_USERNAME`, `DATABASE_PASSWORD`, `DATABASE_NAME` | Postgres connection |
| `IP_ADDRESS` | Optional. Overrides `DATABASE_HOSTNAME` as the Postgres host |
| `READ_TOKEN` | Lets the browser page read. Also typed into the page's unlock screen |
| `WRITE_TOKEN` | For the Mac poller (also allowed to read) |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to call the API, no wildcards. Default `https://gwanwoo.dev`. For local development add `http://127.0.0.1:3000` |
| `TIMEZONE` | Zone the texts are written in, default `America/Toronto`. Decides what "today" means and how Postgres reads stored times |
| `ENABLE_DOCS` | `true` serves `/docs` and `/openapi.json`; off by default |

Start it:

```bash
uvicorn app.main:app --reload
```

## Setup: the Mac (poller)

On the MacBook that receives the texts, in a checkout of this repo (Python 3.11+, `pip install -r requirements.txt`). Give Terminal (or whatever runs the script) **Full Disk Access** so it can read `~/Library/Messages/chat.db`. Create a `.env` with only:

```
RBCHECK_API_URL=https://api.rbcheck.gwanwoo.dev
RBCHECK_WRITE_TOKEN=<the server's WRITE_TOKEN>
```

Optional: `RBC_HANDLE_ID` (default `72272`), `RBC_CHATDB_PATH`, `TIMEZONE`, `POLL_SECONDS` (default 5, minimum 1). No database credentials belong on the Mac. The poller reads `.env` from the directory you run it in, and it refuses a plain `http://` API address (except localhost) so the token can't travel in clear text.

The poller keeps running through problems: if the server is down, returns an error, or `chat.db` is briefly unreadable, it logs the reason and retries with a growing delay (up to 5 minutes), then carries on. A message it cannot parse, or that the server rejects (for example one dated more than a day in the future because the Mac's clock was wrong), is logged and skipped permanently; fix the cause and run `backfill` again to resend everything. It warns if the server has newer message ids than `chat.db` does (for example after Messages was reset), because new texts would then not be sent until their ids catch up.

```bash
python -m app.scripts.backfill   # once: import the whole history (safe to repeat)
python -m app.scripts.poller     # keep running: push new texts as they arrive
```

## Who can do what

| Token | Reads (`GET`) | Writes (`POST`, `PATCH`, `/ingest/*`) |
|---|---|---|
| none / wrong | 401 | 401 |
| `READ_TOKEN` | yes | 403 |
| `WRITE_TOKEN` | yes | yes |

Send it as `Authorization: Bearer <token>`. `/healthz` is the only route without a token. A missing token never reaches the database.

## Upgrading an existing database (timezone)

The API sets the Postgres session timezone to `TIMEZONE`, and ingestion stamps each transaction with an explicit timezone, so new rows are right wherever the Mac or the server runs. Rows stored by the older ingestion were *naive* local times, which Postgres read in whatever its own timezone was at the time. Before running this version against an existing database, run `SHOW timezone;` in `psql`:

- It already shows your zone (e.g. `America/Toronto`): nothing to do.
- It shows `UTC` (typical for Docker): the old rows were stored as if local time were UTC and will now read hours off, some on the wrong day. Back up first, then run this **exactly once** (running it again shifts every row a second time), ideally inside a transaction (`BEGIN; ... COMMIT;`) so you can check a few rows before committing:
  `UPDATE transactions SET transaction_datetime = (transaction_datetime AT TIME ZONE 'UTC') AT TIME ZONE 'America/Toronto';`
- Anything else: work out which zone the old rows were interpreted in and substitute it for `'UTC'` above.

Existing `Balance Warning!` rows from the old parser can be removed: `DELETE FROM transactions WHERE transaction_type = 'Balance Warning!';`

## API

All routes need a token (see above).

| Method | Path | Description |
|---|---|---|
| GET | `/transactions/summary` | Daily/weekly/rolling-7-day/monthly spend |
| GET | `/transactions/` | Paginated list (`offset`, `limit`) |
| GET | `/transactions/date?date_str=MM/DD/YYYY` | Transactions on a given date (defaults to today) |
| GET | `/transactions/weekly` | Since Monday |
| GET | `/transactions/past_7_days` | Last seven days including today |
| GET | `/transactions/month` | Since the 1st of the month |
| GET | `/transactions/date_range?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Arbitrary range |
| GET | `/transactions/merchant?merchant=` | Case-insensitive merchant search |
| GET | `/transactions/price_range?range_start=&range_end=` | Amount range |
| GET | `/transactions/{id}` | One transaction |
| GET | `/insights/today` | Today's digest (recomputed on each call) |
| GET | `/insights/history?days=30` | Recent digests, newest first |
| POST | `/transactions` | Create a manual entry (write token); the server assigns the id |
| PATCH | `/transactions/{id}` | Partially update (write token) |
| GET | `/ingest/cursor` | Highest stored message id (write token) |
| POST | `/ingest/batch` | Push up to 500 parsed transactions (write token) |
| GET | `/healthz` | Health check, no token |

Spending counts purchases and withdrawals, subtracts refunds, and ignores deposits and credit card payments (`app/services/spending.py`). Money values are JSON strings (`"50.00"`).

To rebuild stored digests (for example after editing old transactions) run `python -m app.scripts.digest --days 30`. The default, 2 days, settles yesterday as well as today, so it suits a daily cron.

## Demo server (no Postgres, no real data)

```bash
python -m app.scripts.demo_server   # http://127.0.0.1:8000
```

Runs the real API on an in-memory SQLite database of made-up spending. It prints its (public, fixed) read token for the client's unlock screen and allows the client at `http://127.0.0.1:3000`. Everything resets when it stops.

## Docker

The hosted stack is four containers (`docker-compose.yml`): **Postgres** (data in a named volume), the **API**, a small **digest** job that stores the daily digests every six hours, and **Caddy**, the only one reachable from outside, which serves HTTPS (a certificate is fetched automatically when `SITE_ADDRESS` is a domain name) and refuses request bodies over 1 MB. Postgres and the API publish no ports.

```bash
cp deploy.env.example deploy.env     # fill in the password, both tokens, CORS_ORIGINS, SITE_ADDRESS
docker compose --env-file deploy.env up -d --build
docker compose --env-file deploy.env ps          # db, api, caddy should become healthy
docker compose --env-file deploy.env logs -f api
```

Use the deploy env file on **every** compose command (not your dev `.env`, which holds your real database password). The stack refuses to start without the marker line in `deploy.env`, so forgetting the flag fails loudly. `docker compose ... down -v` deletes the database volume.

To bring your existing data across, follow [docs/MIGRATING-DATA.md](docs/MIGRATING-DATA.md). The Mac poller is not part of the stack; it pushes to the API (see "Setup: the Mac (poller)").

For a quick local trial without Postgres, use the demo server above instead.

## Tests

```bash
pip install pytest
python -m pytest
```

SQLite only: no Postgres, no real messages. They cover the parser, the API, auth on every route, the digests, and the poller against the real API (including server outages, wrong tokens and restarts).
