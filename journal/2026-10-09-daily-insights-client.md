# Showing the daily digest on the page, and what only a real browser could catch

Date: 2026-10-09 | Scope: MILESTONES.md milestone 3 (client `D:\repos\RBCheck-client`, plus a demo server in `D:\repos\RBCheck`) | Outcome: done

Terms from the earlier entries (idempotent, race condition, N+1, settled/final, instant vs wall-clock) are not repeated.

## What

The Ledger page now has a **Daily Digest** section: today's spend with how it compares to your previous 7-day average, a month-so-far and month-end pace, where the money went, any unusually large charges, and a list of past days. Tapping a past day opens it in the ledger table.

To look at it without Postgres or real data, the backend gained `python -m app.scripts.demo_server`: the real API on an in-memory SQLite database filled with made-up spending.

Key files: `js/insights.js` (rendering helpers), `js/app.js` (loading and wiring), `tests/insights.test.mjs` (18 tests), `app/scripts/demo_server.py`.

## Why

The backend digest from milestone 2 is invisible until the page shows it. The demo server exists because "done" for this milestone includes the page actually showing the digest, and there was no way to run the whole thing without your real database.

## How

1. **Pure rendering helpers** (`insights.js`). Functions that take a digest object and return HTML strings. They never touch the page or the network, so Node can import and test them. The file is wrapped so the same code works as a browser global (`Insights`) and as a Node module.
2. **One fetch for the whole page** (`app.js: refreshAll`). The digest is requested in the same `Promise.all` as the summary and month data, so the hero amount and the hero's percentage always come from the same moment.
3. **Escaping everywhere.** Every API value goes through `esc()` before it enters HTML, including numbers and dates.
4. **Failing softly.** `fetchDigest` returns `null` if the request fails (for example against an older backend), and the section hides while the rest of the page works.
5. **Looking at it in Chrome** against the demo server, clicking through, and adding a quick entry.

## Concepts to know

**Pure functions are cheap to test.** Anything that decides what to show can be written as "data in, string out". The 18 tests run in milliseconds with no browser. The code that touches the page (`loadDigest`, click handlers) is thin and gets checked by looking at it. search for: *functional core, imperative shell*.

**Out-of-order responses.** If two requests are in flight and the older one finishes last, it overwrites the newer result. Two quick entries can do this. The cure is a counter: remember which request you are, and ignore your result if a newer one has started (`refreshSeq`, `loadSeq`). search for: *stale response*, *request sequencing*.

**HTML attributes vs. CSS.** The `hidden` attribute only hides an element because the browser's default stylesheet says `[hidden] { display: none }`. Any author rule such as `.pager { display: flex }` has equal or higher priority and silently wins, so the element stays visible. search for: *hidden attribute display override*.

## Hard parts

**Elements marked `hidden` were still showing.**
- *Problem:* in the first screenshot the "‹ Prev / Next ›" buttons were visible in Month view, and after adding an entry the parsed-preview chips stayed on screen with an empty input. Unit tests could never see this.
- *Cause:* `.pager` and `.qa-preview` have `display` rules that override the `hidden` attribute. It predates this milestone.
- *Fix:* one global rule, `[hidden] { display: none !important; }`. I first grepped every use of `hidden` in the HTML and JS (only the digest, the preview and the pager use it) to be sure nothing meant to show could vanish.
- *Lesson:* look at the real page. Tests describe what you remembered to check.

**The demo server fell over once the page got faster.**
- *Problem:* after I moved the digest fetch into `Promise.all`, the page showed "Cannot reach the server". The server log showed `sqlite3.InterfaceError: bad parameter or other API misuse`.
- *Cause:* an in-memory SQLite database lives behind one connection. Five parallel requests share it from different threads, which SQLite does not allow. It only appeared because my change added parallelism.
- *Fix:* a lock so the demo handles one request at a time. I confirmed it by sending nine parallel requests: all 200, no errors. A file-based SQLite database would also work but would write to disk (and your C: drive is nearly full).
- *Lesson:* a change that increases concurrency can break something that "always worked" in a single-user test.

**Two different percentages for the same thing.** The hero said "▲ 75% vs your 7-day average" and the digest said "▲ 83% vs your previous 7-day average". One baseline included today, the other did not. A reviewer would not easily see this from the code; I saw it in one screenshot. The hero now uses the server's figure.

**Driving the browser.** Several of my clicks "did nothing". The cause was smooth scrolling: the screenshot was taken mid-scroll, so my coordinates pointed at a different spot than I thought. I confirmed each click by checking the server log for the request it should have made, rather than trusting the screenshot. Waiting for the scroll to finish fixed it.

## Where a beginner goes wrong

- Declaring a UI change done because the tests pass.
- Building HTML from API data with template strings and no escaping. One missed field (`count` here, found by a reviewer) is enough for a script injection.
- Showing the same quantity in two places computed two ways. Compute it once, on the server, and display it twice.
- Using `hidden` and assuming it always wins over your own CSS.
- Starting servers for a manual check and leaving them running. I stopped both and closed the tab afterwards.

## Decisions

- **Hero delta follows the digest.** Cost: the page now depends on the digest for that number, with the old client calculation as a fallback if the digest fails.
- **Digest fetched inside `refreshAll`** rather than separately. It costs two extra requests per refresh, in exchange for no flicker between inconsistent numbers.
- **Demo server uses a lock**, not a thread-safe database. Simple, and the demo has one user.
- **Demo server cannot reach real Postgres.** It overwrites the database environment variables unconditionally, asserts the database host is the placeholder, replaces the session factory, and prints "DEMO DATA ONLY". A reviewer pointed out the first version would have kept real settings from your shell.
- **`node --test`, no dependencies.** Node's built-in runner, so the client still has no package manager. Note: `node --test tests/` does not work on Node 24 (it treats the folder as a module), so the milestone's check command now reads `node --test`.
- **Deferred:** the 40-simultaneous-requests deadlock in the demo lock (the page fires 5), and phone-width and dark-mode visual checks.

## Verified vs. not

- Verified: 18 client tests and 56 backend tests pass. In Chrome against the demo server: the digest renders with correct numbers (checked by hand: $48.00 + $31.25 = $79.25), tapping a past day opens it (confirmed by the server log), a quick entry returned `201 Created` and updated the ticker, hero, digest and entry count together, and the pager is hidden in Month view. Nine parallel requests: all 200.
- Not verified: the layout at phone width and in dark mode (I changed the CSS but did not look at either), anything against real Postgres, and the quick-entry id range on Postgres (the demo uses SQLite).

## What to look for in review

1. `js/insights.js` — confirm every value that reaches an HTML string passes through `esc()` or is numeric-coerced, including `m.count`.
2. `js/app.js: refreshAll` and `renderDigest` — the `refreshSeq` guard, and that a failed digest never blocks the ledger.
3. `app/scripts/demo_server.py` — the environment override at the top and the assert in `main()`, which are the only things stopping the demo from touching a real database.

## Open questions / next

- Look at the page on a phone-sized window and in dark mode.
- Next milestone: tokens and the Mac-to-AWS push, which is where the API stops being open to anyone.

## Glossary

- **UMD wrapper** — a few lines that let one JavaScript file work both as a browser global and as a Node module.
- **Stale response** — an answer to an old request that arrives after a newer one and overwrites it.
- **Demo server** — the real API running on invented data, for trying the client safely.

## Try it yourself

Delete the last two lines of `css/styles.css` (the `[hidden] { display: none !important; }` rule), then serve the page against the demo server (`python -m app.scripts.demo_server` in the backend, `python -m http.server 3000` in the client, open `http://127.0.0.1:3000/index.html?api=http://127.0.0.1:8000`). Before you look, predict two things you will see wrong on the page.

&nbsp;

*Answer:* the "‹ Prev / Next ›" pager shows in Month view even though the code hides it, and after you submit a quick entry the grey parsed-preview chips stay visible under an empty input. Both elements use the `hidden` attribute, and their `display` rules override it.
