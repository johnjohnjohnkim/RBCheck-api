# RBCheck

A FastAPI backend that turns RBC (Royal Bank of Canada) SMS transaction alerts into a structured, queryable spending ledger.

RBC sends a text for every purchase, withdrawal, deposit, and credit card payment. On macOS those texts land in the iMessage database (`chat.db`). A small agent on an always-on Mac forwards new RBC texts to the API, which parses each one for the amount/merchant/transaction type and stores it in Postgres for the [RBCheck-client](../RBCheck-client) frontend.

## How it works

```
 Mac (always on)                        Server (Docker Compose)
 ┌────────────────────────┐   HTTPS    ┌──────────────────────────────────────────┐
 │ agent/ingest_agent.py  │──────────▶ │ Caddy (HTTPS) ─▶ api (FastAPI) ─▶ db     │
 │ reads chat.db (ro)     │ ingest key │                  parse · dedup · store   │
 └────────────────────────┘            └──────────────────────────────────────────┘
 Browser (RBCheck-client) ── HTTPS ──▶ Caddy ─▶ api
```

1. **Forwarding** (`agent/ingest_agent.py`) reads RBC texts newer than the last one it sent from `chat.db` and posts them, raw, to `POST /ingest`. It asks the API where to resume when it starts, so restarts and outages lose nothing.
2. **Parsing** (`app/sms_parser.py`) extracts the readable text from each message's `attributedBody` blob, then regexes out the dollar amount, merchant name, and transaction type (`Deposit`, `Withdrawal`, `CC Purchase`, `Credit Card Payment`, `Credit Refund`, or a balance-warning marker).
3. **Deduplication** (`app/services/transaction_services.py`) drops a `Withdrawal` that is really the settlement side of a `Credit Card Payment` for the same amount within 60 seconds, whichever of the two arrives first.
4. **Storage**: rows are inserted with the `chat.db` ROWID as `transaction_id`; ones already stored are skipped, so resending is harmless. Transactions entered by hand get negative ids.
5. **API** (`app/routers/transactions.py`) serves summaries and filtered transaction lists to the client. "Today", "this week" and "this month" follow `TIMEZONE`, not the server's clock.
6. **Daily digests** (`app/services/insights.py`) summarise each day: spend against the previous 7-day average, top merchants, unusual charges and the month-end pace. They are stored in `daily_digests` and recomputed whenever a change could affect them, including texts that arrive days late.

Spending everywhere follows `app/services/spending.py`: purchases and withdrawals add, refunds subtract, deposits and card payments don't count.

## Tech stack

- **FastAPI** + **Uvicorn**: HTTP API and ASGI server
- **SQLAlchemy** + **psycopg**: Postgres ORM/driver
- **Pydantic / pydantic-settings**: request/response schemas and env-based config
- **Docker Compose** + **Caddy**: deployment and automatic HTTPS
- **Python standard library only** for the Mac agent

See `requirements.txt` for exact pinned versions.

## Project structure

```
RBCheck-api/
├── app/
│   ├── main.py                       FastAPI app, CORS, routers, /health
│   ├── demo.py                       Scrambled copy of the data for the public demo
│   ├── config.py                     Env settings (pydantic-settings, reads .env)
│   ├── database.py                   Postgres engine/session
│   ├── models.py                     SQLAlchemy Transaction and Users models
│   ├── schemas.py                    Pydantic request/response schemas
│   ├── sms_parser.py                 Extracts amount/merchant/type from iMessage bodies
│   ├── routers/
│   │   ├── transactions.py           /transactions endpoints
│   │   ├── insights.py               /insights daily digests
│   │   └── ingest.py                 /ingest endpoints for the Mac agent (ingest key required)
│   ├── services/
│   │   ├── clock.py                  Today and local-day ranges in TIMEZONE
│   │   ├── insights.py               Daily digests and the spending summary
│   │   ├── spending.py               What counts as spending
│   │   └── transaction_services.py   Parsing, de-duplication, ingest
├── agent/
│   ├── ingest_agent.py               Runs on the Mac; forwards RBC texts to /ingest
│   └── install.sh                    Installs it as a launchd job
├── deploy/
│   ├── Caddyfile                     HTTPS reverse proxy config
│   ├── backup.sh                     Nightly pg_dump, keeps two weeks
│   └── restore.sh                    Loads a dump into the database
├── tests/                            pytest suite (needs a Postgres to run against)
├── docker-compose.yml                db + api + caddy
├── Dockerfile
├── requirements.txt
└── requirements-dev.txt
```

## Configuration

Copy `.env.example` to `.env` and fill it in; the comments in it say how to generate each secret.

| Variable | Description |
|---|---|
| `DATABASE_HOSTNAME` / `_PORT` / `_USERNAME` / `_PASSWORD` / `_NAME` | Postgres connection. Under Compose the host is always `db`. |
| `INGEST_API_KEY` | Shared secret the Mac agent sends as `X-Ingest-Key` |
| `TIMEZONE` | Zone for day boundaries and returned times (default `America/Toronto`) |
| `API_DOMAIN` | Domain Caddy gets a certificate for (Compose only) |
| `DEMO_API_DOMAIN` | Domain of the public demo API (Compose only, default `api.rbcheckdemo.gwanwoo.dev`) |
| `DEMO_SOURCE_DATABASE_NAME` | Set only on the demo API: the real database it copies, scrambled (see below) |

## Running locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # point DATABASE_* at a local Postgres
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

The tests need a Postgres server. By default they use (and create) `rbcheck_test` on `localhost` as your OS user; override with `TEST_DATABASE_HOSTNAME`, `_PORT`, `_USERNAME`, `_PASSWORD` and `_NAME`. They empty every table before each test, so the name must end in `_test`.

## The public demo

`api-demo` in `docker-compose.yml` is a second copy of the API for the public demo site. It has its own database (`rbcheck_demo`, created on first start) and, on startup and then every hour, replaces everything in it with a scrambled copy of the real data (`app/demo.py`):

- about a fifth of the transactions are left out;
- amounts are scaled by one hidden factor and jittered one by one;
- times move by up to 30 hours;
- merchant names become generic stand-ins;
- ids are renumbered.

The scrambling is keyed on `INGEST_API_KEY`, so it can't be undone from this public code. The demo only reads the real database, doesn't take texts from the Mac, and visitors' edits disappear at the next rebuild.

## Deploying to AWS Lightsail

A 1 GB Lightsail instance is enough for Postgres, the API and Caddy.

**1. Create the server**
- Lightsail → Create instance → Linux, **Ubuntu 24.04 LTS**, the 1 GB plan.
- Networking tab: create a **static IP** and attach it. In the IPv4 firewall, add **HTTPS (443)**; keep SSH (22) and HTTP (80, needed for the certificate).
- In your DNS, add **A records** for `api.rbcheck.gwanwoo.dev` and `api.rbcheckdemo.gwanwoo.dev` pointing at the static IP.

**2. Install Docker and start the stack** (over SSH)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && exit        # log back in afterwards
git clone git@github.com:johnjohnjohnkim/RBCheck-api.git && cd RBCheck-api   # private repo: add the server's key as a GitHub deploy key first
cp .env.example .env && chmod 600 .env && nano .env   # fill in every secret
docker compose up -d --build
curl https://api.rbcheck.gwanwoo.dev/health          # {"status":"ok"} once the certificate is issued
```

**3. Move the existing data over**

On the Mac that has the current database:

```bash
pg_dump --format=custom -d <current db name> -f rbcheck.dump
scp rbcheck.dump ubuntu@<static ip>:~/RBCheck-api/
```

On the server:

```bash
deploy/restore.sh rbcheck.dump
```

Check a few recent transactions show the same times as before.

**4. Backups**
- Lightsail → the instance → Snapshots → enable **automatic snapshots**.
- `crontab -e` and add: `15 3 * * * $HOME/RBCheck-api/deploy/backup.sh >> $HOME/rbcheck-backup.log 2>&1`

**5. Switch the Mac over**
- Stop the old `uvicorn` and `poller.py` on the Mac.
- From this repo on the Mac: `agent/install.sh https://api.rbcheck.gwanwoo.dev` and paste `INGEST_API_KEY` when asked.
- Give Full Disk Access to the python path it prints, then follow the log: `tail -f ~/Library/Logs/rbcheck-agent.log`. It should report `Starting after ROWID …` and send anything newer.
- Keep the Mac awake: System Settings → Battery/Energy → "Prevent automatic sleeping when the display is off".

**Updating**: `git pull && docker compose up -d --build` on the server. To update the agent, re-run `agent/install.sh` on the Mac.

## API

There is no login. Only `/ingest` needs a key (`X-Ingest-Key`), so only the Mac can add texts.

Transactions:

| Method | Path | Description |
|---|---|---|
| GET | `/transactions/summary` | Daily/weekly/rolling-7-day/monthly spending (refunds subtract; deposits and card payments don't count) |
| GET | `/transactions/` | Paginated list (`offset`, `limit`) |
| GET | `/transactions/date?date_str=MM/DD/YYYY` | Transactions on a given date (defaults to today) |
| GET | `/transactions/weekly` | Transactions since Monday |
| GET | `/transactions/past_7_days` | Rolling 7-day window |
| GET | `/transactions/month` | Transactions since the 1st of the month |
| GET | `/transactions/date_range?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Transactions in a range, either order (end defaults to today) |
| GET | `/transactions/merchant?merchant=` | Case-insensitive merchant search |
| GET | `/transactions/price_range?range_start=&range_end=` | Transactions within an amount range |
| GET | `/transactions/{id}` | Single transaction |
| POST | `/transactions` | Add a transaction by hand (the server picks the id) |
| PATCH | `/transactions/{id}` | Partially update a transaction |
| GET | `/insights/today` | Today's digest |
| GET | `/insights/history?days=30` | Digests for the last `days` days (1–366), newest first |

Other endpoints:

| Method | Path | Description |
|---|---|---|
| GET | `/ingest/cursor` | Highest stored `chat.db` ROWID (needs `X-Ingest-Key`) |
| POST | `/ingest` | Store a batch of raw texts (needs `X-Ingest-Key`) |
| GET | `/health` | API and database are up |


CORS is restricted to `gwanwoo.dev`, its subdomains, and `localhost`/`127.0.0.1` (see `app/main.py`).
