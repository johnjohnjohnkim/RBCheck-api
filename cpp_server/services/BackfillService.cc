#include "services/BackfillService.h"
#include "services/SmsParser.h"
#include <obfuscate.h>
#include <sqlite3.h>
#include <drogon/orm/DbClient.h>
#include <iostream>
#include <string>
#include <algorithm>
#include <cctype>

namespace rbcheck {

namespace {
std::string toUpper(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), ::toupper);
    return s;
}
} // namespace

int runBackfill(const std::string& sqliteDbPath, const std::string& pgConnStr, int handleId) {
    auto pgDb = drogon::orm::DbClient::newPgClient(pgConnStr, 1);

    sqlite3* sqliteDb = nullptr;
    if (sqlite3_open_v2(sqliteDbPath.c_str(), &sqliteDb, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        std::cerr << "[backfill] Failed to open SQLite DB: " << sqliteDbPath
                  << " — " << sqlite3_errmsg(sqliteDb) << "\n";
        return -1;
    }

    // Query fragments obfuscated — handleId injected at runtime so it's never a literal.
    std::string sqlStr =
        std::string(AY_OBFUSCATE("SELECT m.ROWID, datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime'), m.attributedBody FROM message AS m, handle AS h WHERE h.id = "))
        + std::to_string(handleId)
        + AY_OBFUSCATE(" AND h.ROWID = m.handle_id ORDER BY m.date DESC;");
    const char* sql = sqlStr.c_str();

    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(sqliteDb, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "[backfill] SQLite prepare failed: " << sqlite3_errmsg(sqliteDb) << "\n";
        sqlite3_close(sqliteDb);
        return -1;
    }

    int inserted = 0;
    int skipped  = 0;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int rowId = sqlite3_column_int(stmt, 0);

        const char* dateRaw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        if (!dateRaw) { ++skipped; continue; }
        std::string datetime = std::string(dateRaw) + "+00";

        std::string rawBody;
        if (sqlite3_column_type(stmt, 2) != SQLITE_NULL) {
            const void* blob = sqlite3_column_blob(stmt, 2);
            int blobSize     = sqlite3_column_bytes(stmt, 2);
            if (blob && blobSize > 0)
                rawBody = std::string(reinterpret_cast<const char*>(blob), blobSize);
        }

        if (rawBody.empty()) { ++skipped; continue; }

        std::string parsedText = parseTransaction(toUpper(rawBody));
        if (parsedText.empty()) { ++skipped; continue; }

        auto [amountStr, place, txType] = transactionAnalysis(parsedText);
        if (txType.empty()) { ++skipped; continue; }

        double amount = 0.0;
        if (!amountStr.empty()) {
            try { amount = std::stod(amountStr); }
            catch (...) { ++skipped; continue; }
        }

        try {
            pgDb->execSqlSync(
                std::string(AY_OBFUSCATE(
                    "INSERT INTO transactions "
                    "    (transaction_id, transaction_datetime, amount, place, transaction_type) "
                    "VALUES ($1, $2::timestamptz, $3, $4, $5) "
                    "ON CONFLICT (transaction_id) DO NOTHING")),
                rowId, datetime, amount, place, txType
            );
            ++inserted;
        } catch (const drogon::orm::DrogonDbException& e) {
            std::cerr << AY_OBFUSCATE("[backfill] row write failed, ROWID ") << rowId
                      << ": " << e.base().what() << "\n";
            ++skipped;
        }
    }

    sqlite3_finalize(stmt);
    sqlite3_close(sqliteDb);

    std::cout << "[backfill] Done. Inserted: " << inserted
              << "  Skipped: " << skipped << "\n";
    return inserted;
}

} // namespace rbcheck
