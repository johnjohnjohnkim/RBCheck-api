#!/bin/bash
# Replaces everything in the database with a dump from deploy/backup.sh, or
# with one made elsewhere by: pg_dump --format=custom -d <db> -f rbcheck.dump
#
#   deploy/restore.sh backups/rbcheck-20261012-031500.dump
set -euo pipefail

dump="$(cd "$(dirname "${1:?usage: deploy/restore.sh <file.dump>}")" && pwd)/$(basename "$1")"
cd "$(dirname "$0")/.."

read -rp "This replaces all data in the database with $dump. Type 'yes' to go on: " answer
[[ "$answer" == "yes" ]] || { echo "Nothing changed."; exit 1; }

# --no-owner: the dump's roles (e.g. your Mac username) don't exist here.
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction' < "$dump"
echo "Restored $dump."
