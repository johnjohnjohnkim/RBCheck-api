# Locking the API with tokens, and moving ingestion from "write to the database" to "push over HTTPS"

Date: 2026-10-09 | Scope: MILESTONES.md milestone 4 (backend `D:\repos\RBCheck`) | Outcome: done

Terms from earlier entries (idempotent, race condition, cursor, poison message, N+1, stale response) are not repeated.

## What

The API can now sit on the public internet:
- Every route needs a bearer token. A **read token** lets the page read; a **write token** (held by your Mac) can also write. Without a valid token a request is turned away with 401 before it can reach the database.
- The Mac no longer needs database access. `python -m app.scripts.poller` reads `chat.db`, parses each text, and sends it to the API (`POST /ingest/batch`). It asks the server where it left off (`GET /ingest/cursor`), keeps running through outages, and loses nothing.

Key files: `app/auth.py`, `app/routers/ingest.py`, `app/services/ingestion.py`, `app/scripts/pusher.py`, and three new test files (`test_auth.py`, `test_pusher.py`, `test_hardening.py`). The old `app/scripts/ingest.py` is gone.

## Why

Once the API is hosted, "anyone who can reach it can read and edit your bank data" stops being a theoretical gap. And a hosted database should not have to be reachable from your home Mac. Pushing records through the API means the database port stays closed, and the Mac only needs an address and a token.

## How

1. **Two tokens** (`config.py`, `auth.py`). Both are required settings: the app refuses to start without them, at least 24 characters each, and different from each other. Comparison uses `hmac.compare_digest` so timing doesn't reveal how much of a guess was right.
2. **Auth on whole routers.** `dependencies=[Depends(require_read)]` on the transactions and insights routers, `require_write` on `/ingest` and on POST/PATCH. FastAPI runs those checks before the endpoint's database dependency, so a missing token never opens a session. A read token on a write route gets 403 (known, but not allowed).
3. **Smaller attack surface.** `/docs` and `/openapi.json` are off, CORS lists exact origins (no regex, no cookies), bodies over 1 MB get 413, and `/healthz` is the one open route.
4. **The Mac pushes parsed records** (`pusher.py`). It deliberately imports nothing from `app.config` or `app.database`, so it runs with only an API URL and a token.
5. **The server validates each record on its own** (`ingestion.py`). A bad record is reported in `rejected` and skipped; it never fails the batch. A database failure raises, so the Mac retries.
6. **Dedupe moved server-side**, because only the server can see what is already stored.

## Concepts to know

**Authentication vs. authorization.** Authentication is "who are you?" (a valid token). Authorization is "may you do this?" (a read token cannot write). They map to 401 and 403, and keeping them apart is why the tests walk every route with each kind of token. search for: *401 vs 403*.

**Atomic operations.** An operation is atomic if it either fully happens or doesn't happen at all. Removing a duplicate withdrawal and storing its card payment must be one atomic step: if the process dies between the two, you either double-count or lose data. In a database, "one transaction" gives you this. search for: *database transaction ACID*.

**Backoff.** When a server is down, retrying every 5 seconds from every client makes things worse. Doubling the wait after each failure (up to a cap) is kind to the server and still recovers quickly when it returns. search for: *exponential backoff*.

## Hard parts

**A fix that would have made things worse.** A reviewer found that a card payment deleted *every* matching withdrawal, so two real $300 withdrawals near one payment both vanished. Its suggested crash fix was to re-run the "drop the withdrawal" step whenever a payment already existed. I almost took it, then noticed that every Mac restart replays old messages: the replay would delete the second genuine withdrawal each time. The real fix was atomicity: mark the withdrawal for deletion and store the payment in one database transaction, so there is nothing to "repair" later. *Lesson:* test a suggested repair against the replay path, not just the crash path.

**A test that passed for the wrong reason.** I wrote a replay test, then checked it by temporarily removing the `db.rollback()` it was supposed to protect. The test still passed. A later fix had changed the replay so the dangerous case never occurred. I wrote a second test for the exact scenario (a stored payment replayed alone, next to a genuine withdrawal and an unrelated new record), repeated the removal, and this time it failed with `[1, 4]` instead of `[1, 3, 4]`: the genuine withdrawal had been deleted. *Lesson:* break the code on purpose to see whether the test notices (mutation testing, done by hand).

**The poller could be killed by an unexpected error.** It originally caught only HTTP errors. A locked `chat.db`, an HTML error page that the proxy returned with status 200, or a bad date would have ended the process silently on a Mac nobody is watching. It now catches everything except Ctrl-C, logs a description (never the token), backs off, and re-reads where to resume from the server.

**Two quirks of my own tooling.** Twice a long shell command with several embedded scripts failed to even parse, so nothing ran, and I confirmed that before retrying with the file tools instead. And I once wrote a placeholder file in the wrong place (`D:\Users\`); I removed it immediately and checked that nothing else was there.

## Where a beginner goes wrong

- Putting a secret check in the endpoint code instead of a dependency on the router. The one route you forget is open. The test here walks the app's route table, so a future route without a token fails the suite.
- Comparing tokens with `==`. It works, but leaks timing information.
- Letting one bad record in a batch fail the whole batch. The sender then retries forever and everything behind it is stuck.
- Treating "idempotent retry" as "run the cleanup again". Check what happens when the same request arrives a third time.
- Sending a secret over plain `http://`. The Mac settings refuse it (except for localhost).

## Decisions

- **Both tokens required.** The app won't start with a missing or weak token. Cost: a small hurdle when setting up; benefit: no accidentally open deployment.
- **Read vs. write token** rather than one. The page only holds the read token, so a stolen browser token can't alter data.
- **The Mac parses; the server dedupes.** Parsing needs only the message; dedupe needs the database.
- **Rejected records are skipped permanently** (logged on the Mac). Cost: a record dated in the future because the Mac's clock was wrong is not retried; the README says to fix the cause and run the backfill again.
- **Left out:** rate limiting (random 32-character tokens make guessing impractical), a body-size limit for chunked uploads (the reverse proxy in milestone 6 covers it), and one rare race with two pushers running at once (it fails with a 500 and the retry succeeds).
- **Not read-only for `chat.db`.** I considered opening it read-only. I did not, because I couldn't test that against a live Messages database on a Mac, and it can fail if the helper files are missing. Instead the poller checks the file exists first, so a wrong path no longer creates an empty database.

## Dead ends

- Re-running the withdrawal clean-up for stored payments (see Hard parts): it fixed the crash case and broke the replay case.
- A first replay test that could not fail (see Hard parts).

## Verified vs. not

- Verified: 124 tests pass. Auth is tested by walking every route: none, bad and malformed tokens give 401 with `WWW-Authenticate`; the read token reads every GET route and gets 403 on every write route; docs are 404; CORS allows only the configured origins. Breaking the auth check on purpose made 18 tests fail. The poller is tested against the real API: it sends new texts once, resumes from the server cursor, survives the server being down (backoff 10, 20, 40, capped at 300 seconds), a wrong or read-only token, a database error, a locked `chat.db`, a non-JSON reply and a redirect, and a failure in the middle of a big import. The Mac side is checked to import without any server settings.
- Not verified: anything against real Postgres or a real Mac `chat.db`; all ingest tests run on SQLite, which drops time-zone information, so the aware-timestamp behaviour is reasoned, not tested. The poller has not been run on your Mac. The demo server's client flow is untested because the client does not send a token yet (milestone 5).

## What to look for in review

1. `app/services/ingestion.py: store_transactions` and `_mark_settled_withdrawal` — the pending delete, the single commit inside `insert_transaction`, and the `db.rollback()` when the payment already exists.
2. `app/scripts/pusher.py: run_forever` and `poll_once` — the cursor moves only after the server accepts a chunk; any failure resets it to what the server says.
3. `app/auth.py` and the `dependencies=` on each router — confirm no route is missing one (the walk test is the safety net).

## Open questions / next

- The client sends no token yet, so the page is locked out until milestone 5 adds the unlock screen.
- The poller should run as a background service on the Mac (launchd). Not set up yet.
- After a Messages reset or a new Mac, ids restart low; the poller now warns, but sending would stall until ids catch up. Worth deciding how you would want to handle that.

## Glossary

- **Bearer token** — a secret string sent as `Authorization: Bearer <token>`; whoever holds it gets the access it grants.
- **401 / 403** — "not authenticated" / "authenticated but not allowed".
- **Mutation testing** — deliberately breaking code to confirm the tests notice.
- **Backoff** — waiting longer after each failed retry.
- **CORS origin** — the website address (scheme, host, port) allowed to call the API from a browser.

## Try it yourself

In `app/services/ingestion.py`, find the line `db.rollback()   # already stored: ...` and replace it with `pass`. Then run `D:\repos\RBCheck\venv\Scripts\python.exe -m pytest -q -p no:warnings -p no:cacheprovider tests/test_hardening.py`. Before running, predict which test fails and what data would be lost in real life.

&nbsp;

*Answer:* `test_replaying_a_stored_payment_alone_cannot_delete_a_genuine_withdrawal` fails with `[1, 4] == [1, 3, 4]`. With the rollback gone, the deletion queued for a genuine withdrawal (id 3) is left pending when the already-stored payment is skipped, and the next record's commit writes it. In real life: after a Mac restart replays a batch, a real withdrawal would silently disappear.
