# Teaching the page to ask for a token, and to cope when the answer is "no"

Date: 2026-10-09 | Scope: MILESTONES.md milestone 5 (client `D:\repos\RBCheck-client`) | Outcome: done

Terms from earlier entries (401/403, bearer token, backoff, stale response, atomic) are not repeated.

## What

The page now opens **locked**. Until you paste a token it shows only an unlock dialog and makes no data requests. The read token shows the ledger with editing switched off (a "Read-only" badge, Quick Entry disabled, the edit dialog blocked). The write token shows "Full access". The token lives in this browser only, goes out only in an `Authorization` header, and a **Lock** button forgets it.

Key files: `js/auth.js` (token storage and helpers), `js/api.js` (sends the token, reacts to 401 and 403), `js/app.js` (the unlock flow), `index.html` and `css/styles.css` (the dialog, badge, Lock button), plus `tests/auth.test.mjs` and `tests/api.test.mjs`.

## Why

Milestone 4 made the API refuse requests without a token. Without this milestone the page would simply show "Cannot reach the server" forever.

## How

1. **`auth.js` holds the token** in `localStorage`, falling back to memory if storage is blocked. It has no DOM and no fetch, so Node can test it.
2. **`api.js` sends it** as a header on every request. A 401 forgets the token and re-opens the prompt; a 403 means "valid but read-only" and keeps it.
3. **How does the page know which token it has?** There is no "who am I" endpoint. `GET /ingest/cursor` only accepts the write token, so the page calls it once: 200 means write, 403 means read-only, 401 means invalid. That single probe decides whether to enable editing.
4. **Boot order matters** (`enter()`): probe first, load data only after it succeeds, so nothing sensitive is requested or rendered while locked.
5. **A token is saved only after the server accepts it.** It is held in memory during the check and written to `localStorage` after the probe succeeds.

## Concepts to know

**Capability detection by probing.** When an API doesn't tell you what you're allowed to do, you can call something only privileged callers can reach and read the status code. It works, but it couples the page to that endpoint: if `/ingest/cursor` ever changes, so does the page's idea of access. A dedicated "whoami" endpoint is the cleaner long-term answer; I didn't add one to keep the milestone small. search for: *capability probing*, *whoami endpoint*.

**Stale responses and shared state.** If five requests are in flight with the same token, and the token is rejected, five rejections arrive. If you clear the token and open the prompt on each one, a late rejection can wipe a token the user just typed. The fix is to ask "is this still the token I sent?" before acting on a rejection. search for: *race condition stale token refresh*.

**`inert` and overlays.** Covering the page with an opaque overlay hides it visually but not from the keyboard, copy-paste or screen readers. The `inert` attribute removes an element's whole subtree from focus and interaction. search for: *HTML inert attribute modal dialog*.

## Hard parts

**The token was saved before it was proven.** My first version stored a pasted token immediately. A reviewer pointed out that a typo, or a server hiccup, would leave junk in storage. Now it is written to memory first and persisted only after the probe returns 200 or 403 (a valid token).

**Server problems looked like bad tokens.** If the probe got a 404 or 500, my first version told the user "cannot reach the server" and left no way forward, because the token was gone or hidden. Now only a 401 means "wrong token". Anything else keeps the token for this page and says "Could not check your access (...). Press Unlock to try again." Pressing Unlock with an empty field reuses the token. I verified that in Chrome by starting the page with the API deliberately down and bringing it up afterward.

**A cure that had its own side effect.** To stop Chrome from offering to save the token as a password, I switched the input to `autocomplete="new-password"`. In the browser I realised that value makes Chrome offer to *generate a strong password*, which is wrong for a pasted token. It is now a plain text field masked with CSS (`-webkit-text-security: disc`). I confirmed it shows dots. Cost: older browsers that lack that CSS property would show the token in plain text.

**The browser tool swallowed my first action after every page load.** Four times the first click or keystroke after loading did nothing, which made a working feature look broken (an empty field and no message). I checked each time that the second attempt worked and that the page's behaviour was consistent, rather than changing the code. *Lesson:* when something fails once and works the second time, find out whether the cause is your code or your tooling before editing.

## Where a beginner goes wrong

- Hiding the page with an overlay and calling it locked. The data is still in the DOM, reachable by Tab, find-in-page and screen readers.
- Loading the data first and showing the lock screen on top. Fetch nothing until access is confirmed.
- Treating every failure as an auth failure and wiping the credentials. A server outage is not a wrong password.
- Putting a token in a URL ("just for testing"). URLs end up in history, logs and referrers; headers don't.
- Verifying only the happy path. The interesting behaviour here (server down, token revoked mid-session, double submit) only shows up when you break things on purpose.

## Decisions

- **One field, two token types.** The page works out which one you pasted. Alternative: two fields, or a "write mode" toggle. One field is simpler; the cost is the probe.
- **`localStorage`, not `sessionStorage`.** The token survives closing the tab, which is convenient for a personal tool. Cost: anyone with access to the browser profile, or a script injection on the page, could read it. Mitigation: all API data is escaped, and the read token is the one to use on shared devices. The Lock button clears it.
- **Reload on Lock** rather than clearing every panel by hand. It drops everything held in the page in one step.
- **Read-only is visible, not hidden.** The Quick Entry box is disabled with an explanation, and clicking a row says why it can't be edited.
- **Left as is:** the probe depends on `/ingest/cursor` (no dedicated endpoint), `inert` is relied on with `aria-hidden` as a fallback, and `-webkit-text-security` isn't available everywhere.

## Dead ends

- `autocomplete="new-password"` on a password field (see Hard parts).
- First treating a failed probe like a rejected token.

## Verified vs. not

- Verified: 38 client tests pass, including a 401 clearing the stored token and prompting once, a 403 keeping it, a late 401 for an old token not discarding a newly entered one, probe failures (404, 500, 503, network down) not being treated as auth failures, the token never appearing in a URL, and storage that throws. Breaking the stale-401 guard on purpose made two tests fail. In Chrome against the demo API: the locked page made no data requests; a wrong token gave a message and a cleared field; the read token gave a Read-only page with Quick Entry disabled; a reload kept the token; Lock returned to the prompt; the write token gave Full access and a quick entry saved (`201`); with the API down the retry message appeared, and pressing Unlock again with an empty field succeeded once the API was back; pressing Unlock with nothing pasted says "Paste a token first."
- Not verified: Firefox or Safari (masking and `inert`), a phone-sized window, a real token expiring mid-session (I tested the logic, not a live revocation), and anything against your real AWS-hosted API.

## What to look for in review

1. `js/api.js: request` — the `tokens.get() === sent` check before clearing the token.
2. `js/app.js: enter` and the unlock-form submit handler — the `entering` guard, the `finally` block, and when the token is persisted.
3. `js/app.js: showUnlock` / `hideUnlock` — `inert`, `aria-hidden`, closing the edit dialog and cancelling a pending search while locked.

## Open questions / next

- A small `GET /auth/whoami` on the server would replace the probe and would be easy to add.
- The page is still not deployed anywhere; that, and the API's own hosting, are milestones 6 to 8.

## Glossary

- **Capability probe** — calling an endpoint only some callers may use, to learn what the current caller may do.
- **`inert`** — an HTML attribute that makes an element and its contents unfocusable and non-interactive.
- **Debounce** — waiting for a pause in typing before acting; a pending one can still fire later unless cancelled.
- **Persist** — saving to storage that survives closing the page.

## Try it yourself

In `js/api.js`, change `if (tokens.get() === sent) {` to `if (true) {`, then run `node --test` in `D:\repos\RBCheck-client`. Before running, predict which tests fail, and describe in one sentence what would go wrong for a user in real life.

&nbsp;

*Answer:* two tests fail: "a late 401 for an old token does not discard a newly entered one" and "parallel requests rejected together prompt only once". In real life, after a rejected token you paste a correct one, and a slow rejection of the old token then arrives and wipes the new token and re-opens the prompt, so unlocking seems to fail at random.
