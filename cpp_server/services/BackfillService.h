#pragma once
#include <string>

namespace rbcheck {

// One-time migration from SQLite iPhone messages DB to PostgreSQL.
// sqliteDbPath: path to transactions.db (or ~/Library/Messages/chat.db on macOS).
// pgConnStr: libpq connection string, e.g. "host=... user=... dbname=...".
// Returns number of transactions inserted, or -1 on error.
int runBackfill(const std::string& sqliteDbPath, const std::string& pgConnStr, int handleId);

} // namespace rbcheck
