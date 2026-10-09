# Fixing RBCheck's ingestion bugs, cleaning up the client, and reviewing it all before the first commit

Date: 2026-10-09 | Scope: MILESTONES.md milestone 1 (backend `D:\repos\RBCheck`, client `D:\repos\RBCheck-client`) | Outcome: done

I had no notes on how much backend/Postgres experience you have, so this assumes you are comfortable with Python and HTTP and newer to databases, ingestion pipelines and AWS. Say so if that is wrong and I will re-pitch the next entries.

## What

The backend's parser, poller, backfill and API now behave correctly on the edge cases that used to break them, and have 33 tests (there were none). The client is down from four pages to one (`index.html`, the Daily Ledger), with the API address in one file. Nothing here is new product; it is a clean, tested base for the daily-insights work that follows.

Key files: `app/sms_parser.py`, `app/scripts/ingest.py` (new, shared by the poller and backfill), `app/services/transaction_services.py`, `app/routers/transactions.py`, `app/schemas.py`, `tests/`, and in the client `js/config.js`, `js/api.js`, `js/app.js`.

## Why

You want RBCheck hosted on AWS with daily insights. Hosting a system that silently stops ingesting, crashes on a $1,000 purchase, or returns 500 on bad input would mean debugging those problems remotely. Fixing them first, with tests, means every later milestone starts from something you can trust.

## How

1. **Parser** (`sms_parser.py`). The old code ran `str()` on the raw bytes of the iMessage and searched that text, so it parsed a Python repr like `b'\x24...'`. It now decodes the bytes to text. Amounts keep their thousands commas stripped (`1,234.56` becomes `1234.56`), because `Decimal("1,234.56")` raises. Anything that is not a transaction (balance warnings, "card is due" notices) returns `None` and is never stored.
2. **A cursor for the poller**. The poller needs to know "which iMessages have I already stored?". It uses the highest iMessage `ROWID` in Postgres. Manual entries get ids of 1,000,000,000 and up, and the cursor ignores that range, so a manual entry can never make the poller skip real messages. `poll_once` returns the new cursor, and advances it past messages it deliberately skipped, so they are not re-read every 5 seconds.
3. **Idempotent inserts**. `insert_transaction` does nothing if the id exists, so rerunning the backfill adds nothing.
4. **API hardening** (`routers/transactions.py`). Bad dates give 422 instead of 500, duplicate ids give 409, PATCH can no longer change the primary key, paging has bounds, merchant search treats `%` and `_` literally.
5. **Client**. Deleted the old sidebar UI, renamed the `-alt` files, and routed every request through one error-aware `request()` in `api.js`.

## Concepts to know

**Idempotency.** An operation is idempotent if doing it twice has the same effect as once. Ingestion has to be, because a crash mid-run means you will rerun it, and you cannot know exactly where it stopped. The trick used here is a natural key: the iMessage `ROWID` is the primary key, so "already stored" is a cheap check. search for: *idempotent consumer*, *at-least-once delivery*.

**Poison messages vs. transient failures.** When one item in a stream cannot be processed, you must decide between "skip it and move on" and "stop and retry". Skip a message that can never succeed (an amount like `1.2.3`) or it blocks everything behind it forever. Retry a failure that is not the message's fault (the database is down) or you lose data by advancing past a valid message. The code distinguishes them by exception type. search for: *poison pill message*, *dead-letter queue*.

**Integer ranges.** A Postgres `INTEGER` is 32-bit and tops out at 2,147,483,647. JavaScript's `Date.now()` is about 1,780,000,000,000. The client was sending that as the id. search for: *integer overflow*, *int4 vs int8*.

## Hard parts

**The id that could never have worked.**
- *Problem:* a survey of the code suggested the poller's cursor could be hijacked by manual entries, because `Date.now()` ids are huge.
- *Cause:* tracing it further, the real problem was worse: `transaction_id` is a 32-bit column, so inserting `Date.now()` should fail outright with "integer out of range". Quick-add was very likely broken against Postgres. I confirmed this from the schema; I did not test it against your live database.
- *Fix:* the client sends no id and the server assigns one in the reserved range. My first version of the cursor protection used the wrong ceiling, because I had assumed the ids were bigger than the column allows.
- *Lesson:* when two bugs seem to fit one story, check the types and limits at each boundary. A bug upstream can make the "interesting" bug downstream unreachable.

**Two quick-adds at once.**
- *Problem:* the server picked "highest manual id + 1". Two simultaneous requests pick the same number, and the second fails.
- *Cause:* a classic race condition: read, then write, with nothing preventing someone else from writing in between.
- *Fix:* retry up to three times on a collision, plus a disabled button while a request is in flight. A Postgres sequence would remove the race entirely; I chose the retry because it needs no schema change.
- *Lesson:* "check then insert" is never safe on its own. Let the database's uniqueness constraint be the judge, and handle its error.

## Where a beginner goes wrong

- Treating every exception the same: either a bare `except: continue` (silently loses data when the database blips) or no handling at all (one bad row freezes the pipeline). Decide per exception type what is safe to skip.
- Catching an error and returning `None` without checking what `None` means to the caller. `insert_transaction` returning `None` means "already stored", which the poller counts as success. That is only safe because the sole possible integrity error is a duplicate primary key.
- Testing with a database that is more forgiving than production. The API tests run on in-memory SQLite, which does not enforce `Numeric(10,2)` or 32-bit integers.
- Writing the tests after "knowing" the code works. Several tests here exist only because a reviewer asked "what happens if…".

## Decisions

- **No Alembic migrations.** Options: add migrations now, or keep `create_all` and avoid schema changes. I avoided changes (manual ids live in a numeric range, not a new column). Cost: a future schema change will need a migration tool then.
- **Kept chat.db opening in normal mode, not read-only.** The reviewer suggested `mode=ro`. I did not do it: a read-only open of a live WAL-mode database can fail if the `-shm` file is missing, and I could not test that on a Mac. Cost: the poller technically has write access it never uses.
- **Deferred rather than fixed.** Server timezone, the server/client mismatch on how refunds count, a withdrawal arriving before its card payment, auth, and per-row commits. Each is real; each is owned by a later milestone, and a fix now would have been done twice.
- **Review loop of two rounds.** Round one found 12 issues; I fixed the ones in scope. Round two checked the fixes and found two low-severity edge cases, which I also fixed. I stopped there because the second report said nothing serious remained.
- **Stage files by name.** There is an empty `docker.yaml` in the repo that is not mine, so I will not use `git add .`.

## Dead ends

- Tried to run the work in a separate git worktree so your checkout stayed untouched. The tool only accepts worktrees of the repository the session started in, and you asked me to work in the real repo anyway. I removed the worktree and branch I had created.
- Tried to install test dependencies into a fresh virtual environment; you declined that and I used the existing one with `pytest` added.

## Verified vs. not

- Verified: 33 tests pass. The parser handles all 4,535 real RBC messages in your local copy (39 correctly ignored, no bad amounts, no commas). Client JavaScript passes `node --check`; the config override rules and the API error messages were checked in Node with fakes.
- Not verified: nothing was run against your real Postgres, the poller was never run against a live `chat.db`, and the page was not opened in a browser. The int32 overflow is reasoned from the schema, not reproduced. `pagination is stable` is a weak test on SQLite, which returns ties in insertion order anyway.

## What to look for in review

1. `app/scripts/ingest.py: ingest_rows` — which exceptions are caught (only `ValidationError` and `DataError`) and which propagate. This is the line between "skip" and "retry", so a mistake here either loses data or freezes ingestion.
2. `app/services/transaction_services.py: insert_transaction` — the retry loop: check that every path returns, raises or continues, and that the session is rolled back before each retry.
3. `js/app.js: loadView` — the sequence counter that discards an older response when a newer view has been requested.

## Open questions / next

- Run the tests and try quick-add against your real Postgres once.
- Delete the stored `Balance Warning!` rows from the old parser (the SQL is in the earlier chat).
- Next milestone: the daily-insights backend, which also fixes the timezone and refund-counting mismatch.

## Glossary

- **Cursor** — a saved position ("last message id I processed") that lets a loop resume where it stopped.
- **Idempotent** — safe to repeat; the second run changes nothing.
- **Race condition** — a bug where the result depends on the timing of two simultaneous operations.
- **Poison message** — an input that can never be processed successfully and, handled badly, blocks everything behind it.
- **WAL** — SQLite's write-ahead log; the extra files (`-wal`, `-shm`) beside a live database.
- **422 / 409** — HTTP "your input is invalid" and "that conflicts with existing data".

## Try it yourself

In `app/schemas.py`, change `lt=MANUAL_ID_FLOOR` in `TransactionCreate` to `lt=2**31`, then run `D:\repos\RBCheck\venv\Scripts\python.exe -m pytest -q -p no:warnings -p no:cacheprovider`. Before you run it, predict which test fails and what real-world bug it was guarding against.

&nbsp;

*Answer:* `test_explicit_id_in_the_manual_range_is_rejected` fails: a client can again POST an id like 1,500,000,000. The worst case is an id of 2,147,483,647, after which the next server-assigned id would be 2,147,483,648, which overflows the column, so every later quick-add fails until that row is deleted.
