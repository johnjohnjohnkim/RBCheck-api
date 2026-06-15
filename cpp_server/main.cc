#include <drogon/drogon.h>
#include "services/BackfillService.h"
#include <cstdlib>
#include <iostream>
#include <string>

static std::string env(const char* name, const char* fallback) {
    const char* val = std::getenv(name);
    return val ? val : fallback;
}

int main(int argc, char* argv[]) {
    // --backfill [path/to/transactions.db]
    // Runs the one-time SQLite → PostgreSQL migration and exits.
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--backfill") {
            std::string dbPath = (i + 1 < argc) ? argv[i + 1] : "transactions.db";

            std::string host   = env("DATABASE_HOSTNAME", "127.0.0.1");
            std::string port   = env("DATABASE_PORT",     "5432");
            std::string user   = env("DATABASE_USERNAME", "postgres");
            std::string pass   = env("DATABASE_PASSWORD", "");
            std::string dbname = env("DATABASE_NAME",     "rbcheck");

            std::string connStr =
                "host="     + host   +
                " port="    + port   +
                " user="    + user   +
                " password="+ pass   +
                " dbname="  + dbname;

            int n = rbcheck::runBackfill(dbPath, connStr);
            return n >= 0 ? 0 : 1;
        }
    }

    // ── HTTP server ──────────────────────────────────────────────────────────
    std::string host   = env("DATABASE_HOSTNAME", "127.0.0.1");
    int         port   = std::stoi(env("DATABASE_PORT", "5432"));
    std::string user   = env("DATABASE_USERNAME", "postgres");
    std::string pass   = env("DATABASE_PASSWORD", "");
    std::string dbname = env("DATABASE_NAME",     "rbcheck");

    drogon::app()
        .addListener("0.0.0.0", 8080)
        .setThreadNum(0)           // 0 = one thread per CPU core
        .createDbClient(
            "postgresql",
            host,
            static_cast<unsigned short>(port),
            dbname,
            user,
            pass,
            5                      // connection pool size
        )
        .run();

    return 0;
}
