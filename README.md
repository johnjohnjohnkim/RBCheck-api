# RBCheck

## Configuration

No secrets are compiled into the binary. All runtime config is supplied via environment variables.

Copy the template and fill in your values:

```bash
cp cpp_server/.env.example cpp_server/.env
chmod 600 cpp_server/.env   # restrict read access
$EDITOR cpp_server/.env
```

The server loads `.env` from the working directory at startup. Real environment variables always override `.env` values.

### Required variables

| Variable | Description |
|---|---|
| `DATABASE_HOSTNAME` | PostgreSQL host |
| `DATABASE_PORT` | PostgreSQL port (typically 5432) |
| `DATABASE_USERNAME` | PostgreSQL role |
| `DATABASE_PASSWORD` | PostgreSQL password |
| `DATABASE_NAME` | Database name |

### Optional variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_POOL_SIZE` | `5` | Drogon connection pool size |
| `LISTEN_HOST` | `0.0.0.0` | HTTP bind address |
| `LISTEN_PORT` | `8080` | HTTP bind port |

### Backfill-only variables

| Variable | Description |
|---|---|
| `RBC_HANDLE_ID` | iMessage handle ROWID for the RBC SMS shortcode |
| `RBC_CHATDB_PATH` | Path to `chat.db` (default: `$HOME/Library/Messages/chat.db`) |

### Setting variables without a .env file

```bash
# Export in shell
export DATABASE_HOSTNAME=localhost DATABASE_PORT=5432 ...

# Or inline for a single run
DATABASE_HOSTNAME=localhost DATABASE_PORT=5432 ... ./rbcheck

# systemd: use an EnvironmentFile= pointing to your .env
```