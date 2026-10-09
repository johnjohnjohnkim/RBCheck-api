# Moving your existing data into the hosted database

You run these steps yourself. Nothing here is automatic, and nothing touches your data until you type it. Every `docker compose` command needs `--env-file deploy.env`.

The goal: copy the transactions from your current Postgres (on the Mac or at home) into the new Postgres that runs inside the Docker stack (`docker-compose.yml`), then point the Mac poller at the API.

**Before you start**
- Start the stack with your `deploy.env` (see `deploy.env.example`): `docker compose --env-file deploy.env up -d --build`. Wait until `docker compose --env-file deploy.env ps` shows `db` and `api` as healthy.
- **Stop the Mac poller** (and anything else writing to either database) until you finish. The restore replaces the table, so anything pushed meanwhile would be lost or cause errors.
- A dump contains your real transactions. Keep it out of git (`*.dump` is ignored) and delete it when done.
- Use a `pg_dump` of **version 16 or lower**: the database in the stack is Postgres 16 and its `pg_restore` cannot read a dump made by a newer version. Check with `pg_dump --version`.

## 1. Check the old database's timezone (important)

On the **old** database, in `psql`:

```sql
SHOW timezone;
```

- Shows your zone (e.g. `America/Toronto`): nothing to adjust; carry on.
- Shows `UTC`: the old times were stored as if local time were UTC and will read hours off. After the restore, run the one-time fix **exactly once** (see "Upgrading an existing database (timezone)" in the README).

## 2. Dump the old database

On a machine that can reach it (replace the placeholders):

```bash
pg_dump -Fc -h <old-host> -p <port> -U <old-user> -d <old-dbname> -t transactions -f rbcheck.dump
```

`-Fc` is a compact format `pg_restore` can read; `-t transactions` copies only that table (the digests are rebuilt).

## 3. Restore into the stack

Put `rbcheck.dump` next to `docker-compose.yml`. These commands work the same in PowerShell, cmd and bash (no `<` redirection):

```bash
docker compose --env-file deploy.env cp rbcheck.dump db:/tmp/rbcheck.dump
docker compose --env-file deploy.env exec db pg_restore -U rbcheck -d rbcheck --no-owner --clean --if-exists --single-transaction --exit-on-error /tmp/rbcheck.dump
docker compose --env-file deploy.env exec db rm /tmp/rbcheck.dump
```

`--single-transaction --exit-on-error` makes it all-or-nothing: if anything fails you keep what you had instead of a half-restored table. `--clean` replaces the table the API created with the old table's definition, so check the result next.

## 4. Check it

```bash
docker compose --env-file deploy.env exec db psql -U rbcheck -d rbcheck -c "\d transactions"
```

`transaction_datetime` must say **timestamp with time zone**. If it says `timestamp without time zone`, the old table was an older design; stop and ask before using the data, because the API and the digests assume the timezone-aware column.

```bash
docker compose --env-file deploy.env exec db psql -U rbcheck -d rbcheck -c "SELECT count(*), min(transaction_datetime AT TIME ZONE 'America/Toronto'), max(transaction_datetime AT TIME ZONE 'America/Toronto') FROM transactions;"
```

Compare the count and dates with the old database (`AT TIME ZONE` is there because `psql` inside the stack shows times in UTC). Then, optionally, remove balance warnings stored by the old parser, and rebuild the digests so history is computed from the restored data:

```bash
docker compose --env-file deploy.env exec db psql -U rbcheck -d rbcheck -c "DELETE FROM transactions WHERE transaction_type = 'Balance Warning!';"
docker compose --env-file deploy.env exec api python -m app.scripts.digest --days 90
```

If step 1 said `UTC`, run the one-time timezone fix from the README the same way, once:

```bash
docker compose --env-file deploy.env exec db psql -U rbcheck -d rbcheck -c "UPDATE transactions SET transaction_datetime = (transaction_datetime AT TIME ZONE 'UTC') AT TIME ZONE 'America/Toronto';"
```

## 5. Point the Mac poller at the API

Follow "Setup: the Mac (poller)" in the README (`RBCHECK_API_URL` and `RBCHECK_WRITE_TOKEN`) and start it again. On start the poller asks the API for the last message it has and resumes from there, so nothing is sent twice. You can run `python -m app.scripts.backfill` once to be sure nothing is missing; it only adds what the server doesn't already have.

## 6. Clean up

Delete `rbcheck.dump`. Keep the old database for a while after you have started using the new one. Back up the new one regularly (the AWS runbook covers this); `docker compose down -v` deletes its data.
