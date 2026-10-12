#!/bin/bash
# Dumps the database to backups/ and keeps two weeks of dumps. Run nightly
# from the server's crontab (crontab -e), e.g.:
#
#   15 3 * * * $HOME/RBCheck-api/deploy/backup.sh >> $HOME/rbcheck-backup.log 2>&1
#
# These live on the same disk as the database, so they guard against
# mistakes, not a lost server; Lightsail's automatic snapshots cover that.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups
file="backups/rbcheck-$(date +%Y%m%d-%H%M%S).dump"

# Write to a temp name first so a failed dump never looks like a good one.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$file.partial"
mv "$file.partial" "$file"

find backups -name 'rbcheck-*.dump' -mtime +14 -delete
echo "$(date '+%F %T') wrote $file ($(du -h "$file" | cut -f1))"
