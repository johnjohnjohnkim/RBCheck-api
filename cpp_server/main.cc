#include <drogon/drogon.h>
#include "services/BackfillService.h"
#include <obfuscate.h>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

// ── Config loader ─────────────────────────────────────────────────────────────

// Parse .env file and populate environment. Real env vars always win (no-overwrite).
static void loadDotEnv(const char* path = ".env") {
    std::ifstream f(path);
    if (!f.is_open()) return;
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        setenv(line.substr(0, eq).c_str(), line.substr(eq + 1).c_str(), 0);
    }
}

// Required string var — prints "FATAL: NAME is not set" and exits(1) if absent/empty.
static std::string requireEnv(const char* name) {
    const char* v = std::getenv(name);
    if (!v || v[0] == '\0') {
        std::cerr << "FATAL: " << name << " is not set\n";
        std::exit(1);
    }
    return v;
}

// Required integer var — validates parse, exits(1) with a named error on failure.
static int requireEnvInt(const char* name) {
    std::string s = requireEnv(name);
    try {
        size_t pos;
        int v = std::stoi(s, &pos);
        if (pos != s.size()) throw std::invalid_argument("trailing characters");
        return v;
    } catch (...) {
        std::cerr << "FATAL: " << name << " must be an integer (got \"" << s << "\")\n";
        std::exit(1);
    }
}

// Optional var with fallback.
static std::string optEnv(const char* name, const char* fallback) {
    const char* v = std::getenv(name);
    return (v && v[0] != '\0') ? v : fallback;
}

// ─────────────────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    loadDotEnv();

    // ── --backfill [path/to/chat.db] ─────────────────────────────────────────
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--backfill") {
            std::string dbPath;
            if (i + 1 < argc) {
                dbPath = argv[i + 1];
            } else {
                const char* env_path = std::getenv("RBC_CHATDB_PATH");
                if (env_path && env_path[0]) {
                    dbPath = env_path;
                } else {
                    // Default path constructed at runtime — literal not baked into binary
                    const char* home = std::getenv("HOME");
                    if (!home || !home[0]) {
                        std::cerr << "FATAL: RBC_CHATDB_PATH is not set\n";
                        std::exit(1);
                    }
                    dbPath = std::string(home) + AY_OBFUSCATE("/Library/Messages/chat.db");
                }
            }

            int handleId = requireEnvInt("RBC_HANDLE_ID");

            std::string connStr =
                "host="      + requireEnv("DATABASE_HOSTNAME") +
                " port="     + requireEnv("DATABASE_PORT")     +
                " user="     + requireEnv("DATABASE_USERNAME") +
                " password=" + requireEnv("DATABASE_PASSWORD") +
                " dbname="   + requireEnv("DATABASE_NAME");

            int n = rbcheck::runBackfill(dbPath, connStr, handleId);
            return n >= 0 ? 0 : 1;
        }
    }

    // ── HTTP server ───────────────────────────────────────────────────────────
    std::string listenHost = optEnv("LISTEN_HOST", "0.0.0.0");
    int         listenPort = std::stoi(optEnv("LISTEN_PORT", "8080"));
    int         dbPort     = requireEnvInt("DATABASE_PORT");
    int         poolSize   = std::stoi(optEnv("DATABASE_POOL_SIZE", "5"));

    drogon::app()
        .addListener(listenHost, listenPort)
        .setThreadNum(0)
        .createDbClient(
            "postgresql",
            requireEnv("DATABASE_HOSTNAME"),
            static_cast<unsigned short>(dbPort),
            requireEnv("DATABASE_NAME"),
            requireEnv("DATABASE_USERNAME"),
            requireEnv("DATABASE_PASSWORD"),
            poolSize
        )
        .run();

    return 0;
}
