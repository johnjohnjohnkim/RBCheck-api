# Daily spending digests for RBCheck, and the timezone and caching bugs they flushed out

Date: 2026-10-09 | Scope: MILESTONES.md milestone 2 (backend `D:\repos\RBCheck`) | Outcome: done, with one gap: nothing was run against real Postgres

Terms defined in the first entry (idempotent, race condition, cursor, poison message, 409/422) are not repeated here.

## What

RBCheck can now answer "how did I spend today compared to usual?". `GET /insights/today` returns one digest: spend today, how it compares with the previous 7-day average, the top three merchants, the month so far and a month-end projection, and any unusually large charges. `GET /insights/history?days=30` returns the same for recent days. Digests are saved in a new `daily_digests` table so the history persists.

Along the way "today" stopped depending on the server's clock, and the server and client finally agree on what counts as spending.

Key files: `app/services/insights.py` (the digest and caching logic), `app/services/clock.py` (timezone helpers), `app/services/spending.py` (what counts as spending), `app/routers/insights.py`, `app/scripts/digest.py` (for a daily cron), `app/scripts/ingest.py` (timestamps), `tests/test_insights.py`.

## Why

This is the feature you started the project for: RBC gives no daily view, TD does. It also exposed two problems that would have bitten the moment the API moved to AWS: "today" came from the server's clock (UTC on most servers, so the day would roll over at about 8pm Toronto time), and the summary and the web page disagreed on whether refunds count.

## How

1. **One definition of spending** (`spending.py`). Deposits and credit card payments are money moving, so they count as 0. Refunds subtract. Everything else adds. `/transactions/summary`, the digests and the client all follow this now. Before, the server added refunds to spending while the client subtracted them.
2. **Days belong to a timezone** (`clock.py`). `today()` and `local_date()` convert to `TIMEZONE` (default `America/Toronto`) before taking a date. The database connection also sets Postgres's session timezone to the same zone, so the day boundaries the API queries with mean the same thing to Postgres.
3. **The digest** (`insights.py: digest_payload`). It takes already-loaded transactions grouped by local day and does only arithmetic. Keeping the database out of it made the maths easy to test with a few hand-written rows.
4. **Storing and reusing digests** (`history`, `_save`). History loads the transactions once for the whole range, computes whatever is missing or out of date, and saves it in a single commit.
5. **Ingestion** (`ingest.py`). It now reads the message time as UTC seconds and attaches the app timezone explicitly, instead of asking SQLite for the Mac's "localtime".

## Concepts to know

**Wall-clock time vs. an instant.** "11:30pm on July 4" is a wall-clock time and means nothing until you know where. "03:30 UTC on July 5" is an instant: one moment everywhere. The old code stored wall-clock times with no zone attached ("naive"), and Postgres guessed the zone from its own setting. Storing the instant with an explicit zone removes the guess. search for: *naive vs aware datetime*, *timestamptz*.

**Cache invalidation: when is a stored answer still true?** Storing a computed digest is a cache. A cache is only safe if you know when it goes stale. Today's digest is stale within minutes. Yesterday's is stale until the last text arrives. Any digest is stale if the code that computes it changes. I encoded those three rules as `final`, `settled` and `v` in the stored payload. search for: *cache invalidation*, *write-through vs. TTL*.

**N+1 queries.** Fetching a list with one query and then one more query per item turns 30 days into 31 round trips (or 360 with the 90-day lookback). The fix is to fetch once and group in memory. A test now counts the SQL statements a cold 60-day history makes (at most 8). search for: *N+1 query problem*.

## Hard parts

**The first version served stale digests forever.**
- *Problem:* a reviewer pointed out that opening `/insights/today` at 10am saved a row; the next day, history found that row for "yesterday" and served it unchanged. Late texts and edits never showed up.
- *Cause:* "a row exists" was treated as "the answer is final".
- *Fix:* a row is reused only if it was computed after its day ended, at least two hours after (so the poller has caught up), and with the current code version. Otherwise it is recomputed.
- *Lesson:* before saving a computed result, write down the exact conditions under which it becomes wrong.

**My own fix had an inconsistency, and a test caught it.** After adding the two-hour rule, one test failed: a digest computed "mid-day" was being cached. I had decided "settled" using the real clock but "final" using the date the caller passed in, so they could disagree. Fix: settled can only be true if final is. It was a small bug, but only because a test happened to cross the two clocks.

**Changing the database session timezone rewrites the meaning of old rows.**
- *Problem:* if your Postgres previously ran in UTC, the old rows hold Toronto wall-clock times that were read as UTC. Setting the session to Toronto would shift every old row by 4 to 5 hours, some onto the wrong day.
- *Fix:* new rows are stamped with an explicit zone so they are right regardless. For old rows I could not know the old setting, so the README tells you to run `SHOW timezone;` first, and gives a one-time `UPDATE` only if the answer is `UTC`, with a warning to run it exactly once.
- *Lesson:* a config change that reinterprets stored data is a data migration, even if it is one line of code.

**Vacuous tests.** Two tests I wrote first passed for the wrong reasons: one ended with `... or True`, and the other tested a "stale row" on a day before the first transaction, which the code excludes, so it never reached the case. Passing is not evidence unless the test would fail without the feature. I rewrote both to assert exact outcomes.

## Where a beginner goes wrong

- Using `date.today()` on a server. It returns the server's date, not the user's. Always say which timezone a date is in.
- Comparing a naive datetime with an aware one: Python raises an error (`TypeError`), but databases quietly pick an interpretation. Test with data near midnight.
- Dividing "month so far" by "days so far" to project a month, without asking whether today is finished. On the 1st it multiplies one partial day by 31, so the projection is now null until three full days have passed.
- Looping over days and running a query per day inside a request handler.
- Writing the expected values in a test by running the code and copying its output. The numbers in `test_digest_math` were worked out by hand first (for example 6 + 4 + 50 − 10 = 50).

## Decisions

- **Store digests vs. compute on every request.** Computing is cheap for one user. I stored them because you asked for tracked history, and past days then don't change underneath you. Cost: the cache rules above.
- **Projection is null early in the month** rather than a wild number. Cost: the client must show "not enough data yet".
- **Rolling seven days now means seven days including today.** It used to span eight calendar days while the client divided by seven.
- **Kept substring matching in `spend_value`** ("credit", "payment", "deposit"). It mirrors the client, which also accepts free-form types from quick-add. A strict allow-list would break those.
- **Deferred:** merchant-name normalisation (so "STARBUCKS #123" and "#456" count as one merchant), early-history dilution of the 7-day average, and the projection skew in a user's very first month.
- **Money serialises as strings** ("50.00"), as the existing summary already did. The client must convert.

## Verified vs. not

- Verified: 56 tests pass, including hand-calculated digest numbers, the 11:30pm boundary (a stored 23:30 wall-clock time lands on its own day; a UTC instant of 03:30 on July 5 lands on July 4 in Toronto), stale-then-final recompute, a payload from an older version, a simulated lost save race, the statement-count cap, an invalid `TIMEZONE`, and ingestion stamping Toronto time from a UTC value.
- Not verified: everything above ran on SQLite. Docker Desktop was not running, so I could not test against Postgres, which is where timestamp handling, the session-timezone option and the JSONB column actually matter. I also did not run the digest script against your real database. Milestone 6 (Docker) is the first chance to check this properly.

## What to look for in review

1. `insights.py: history` and `_save` — the reuse rule (`_reusable`), and that each digest's data is captured before the commit (committing expires ORM objects, so reading them afterwards would trigger one query per row).
2. `ingest.py: ingest_rows` — `datetime.fromtimestamp(unix_seconds, tz=app_tz())`. Check that the chat.db date arithmetic (nanoseconds since 2001 → Unix seconds) is right; it was only verified with a constructed value.
3. `clock.py: settled` — the two-hour window and the end-of-day calculation in the app timezone.

## Open questions / next

- Run `SHOW timezone;` on your Postgres before you deploy this (see README).
- `GET` requests write to the database (today's row is rewritten every call). Fine for one user; revisit if it ever matters.
- Next milestone: show the digest in the client.

## Glossary

- **Digest** — the stored summary of one day's spending.
- **Final / settled** — final: the day is over. Settled: it has been over for at least two hours, so late texts are in and the stored copy can be trusted.
- **Wall-clock time** — a date and time with no timezone attached.
- **Instant** — one exact moment, independent of timezone.
- **Session timezone** — the zone a Postgres connection uses to read naive timestamps and display aware ones.
- **N+1 queries** — one query for a list plus one more per item.
- **JSONB** — Postgres's indexed binary JSON column type.

## Try it yourself

In `app/services/clock.py` change `SETTLE_HOURS = 2` to `SETTLE_HOURS = 0`, then run `D:\repos\RBCheck\venv\Scripts\python.exe -m pytest -q -p no:warnings -p no:cacheprovider tests/test_insights.py`. Before running, predict which test fails and what real situation it protects against.

&nbsp;

*Answer:* `test_a_day_settles_two_hours_after_it_ends` fails on its first assertion (at 05:59 UTC, only 1h59 after Toronto midnight, the day would now count as settled). In real life this is the 00:05 problem: a digest for yesterday gets cached and served forever before the poller has ingested yesterday's last texts.
