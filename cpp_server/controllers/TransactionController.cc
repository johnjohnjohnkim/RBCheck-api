#include "controllers/TransactionController.h"
#include <obfuscate.h>
#include <drogon/drogon.h>
#include <json/json.h>
#include <ctime>
#include <string>
#include <vector>
#include <memory>
#include <sstream>
#include <iomanip>

// ─── Internal helpers ────────────────────────────────────────────────────────

namespace {

// Decrypted once on first call; pointer valid for process lifetime.
static const char* selectCols() noexcept {
    return AY_OBFUSCATE(
        "transaction_id, "
        "transaction_datetime::text, "
        "amount::float8, "
        "place, "
        "transaction_type");
}

Json::Value rowToJson(const drogon::orm::Row& row) {
    Json::Value obj;
    obj["transaction_id"]       = row["transaction_id"].as<int>();
    obj["transaction_datetime"] = row["transaction_datetime"].as<std::string>();
    obj["amount"]               = row["amount"].as<double>();
    obj["place"]                = row["place"].as<std::string>();
    obj["transaction_type"]     = row["transaction_type"].as<std::string>();
    return obj;
}

Json::Value resultToArray(const drogon::orm::Result& result) {
    Json::Value arr(Json::arrayValue);
    for (const auto& row : result)
        arr.append(rowToJson(row));
    return arr;
}

drogon::HttpResponsePtr jsonResp(Json::Value body,
                                  drogon::HttpStatusCode code = drogon::k200OK) {
    auto resp = drogon::HttpResponse::newHttpJsonResponse(std::move(body));
    resp->setStatusCode(code);
    return resp;
}

drogon::HttpResponsePtr errResp(const std::string& detail,
                                 drogon::HttpStatusCode code) {
    Json::Value err;
    err["detail"] = detail;
    return jsonResp(std::move(err), code);
}

std::string todayLocal() {
    std::time_t t = std::time(nullptr);
    std::tm tm{};
    localtime_r(&t, &tm);
    char buf[11];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d", &tm);
    return buf;
}

std::string toPostgresDate(const std::string& s) {
    if (s.size() == 10 && s[2] == '/' && s[5] == '/')
        return s.substr(6, 4) + "-" + s.substr(0, 2) + "-" + s.substr(3, 2);
    return "";
}

void execList(const std::string& sql,
              std::function<void(const drogon::HttpResponsePtr&)> cb) {
    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) { cb(jsonResp(resultToArray(r))); },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        }
    );
}

} // anonymous namespace

// ─── GET /api/v1/transactions/date?date_str=MM/DD/YYYY ───────────────────────

void TransactionController::getByDate(const drogon::HttpRequestPtr& req, Callback&& cb) {
    std::string raw    = req->getParameter("date_str");
    std::string pgDate = raw.empty() ? todayLocal() : toPostgresDate(raw);

    if (pgDate.empty()) {
        cb(errResp("date_str must be MM/DD/YYYY", drogon::k400BadRequest));
        return;
    }

    std::string dayStart = pgDate + " 00:00:00";
    std::string dayEnd   = pgDate + " 23:59:59.999999";

    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE transaction_datetime >= $1"
                     "   AND transaction_datetime <= $2"
                     " ORDER BY transaction_datetime");

    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) { cb(jsonResp(resultToArray(r))); },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        },
        dayStart, dayEnd
    );
}

// ─── GET /api/v1/transactions/weekly ─────────────────────────────────────────

void TransactionController::getWeekly(const drogon::HttpRequestPtr&, Callback&& cb) {
    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE transaction_datetime >= date_trunc('week', CURRENT_TIMESTAMP)"
                     " ORDER BY transaction_datetime");
    execList(sql, std::move(cb));
}

// ─── GET /api/v1/transactions/past_7_days ────────────────────────────────────

void TransactionController::getPast7Days(const drogon::HttpRequestPtr&, Callback&& cb) {
    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE transaction_datetime >= CURRENT_TIMESTAMP - INTERVAL '7 days'"
                     " ORDER BY transaction_datetime");
    execList(sql, std::move(cb));
}

// ─── GET /api/v1/transactions/monthly ────────────────────────────────────────

void TransactionController::getMonthly(const drogon::HttpRequestPtr&, Callback&& cb) {
    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE transaction_datetime >= date_trunc('month', CURRENT_TIMESTAMP)"
                     " ORDER BY transaction_datetime");
    execList(sql, std::move(cb));
}

// ─── GET /api/v1/transactions/biweekly ───────────────────────────────────────

void TransactionController::getBiweekly(const drogon::HttpRequestPtr&, Callback&& cb) {
    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE transaction_datetime >= CURRENT_TIMESTAMP - INTERVAL '14 days'"
                     " ORDER BY transaction_datetime");
    execList(sql, std::move(cb));
}

// ─── GET /api/v1/transactions/date_range?start_date=&end_date= ───────────────

void TransactionController::getDateRange(const drogon::HttpRequestPtr& req, Callback&& cb) {
    std::string startPg = toPostgresDate(req->getParameter("start_date"));
    std::string endPg   = toPostgresDate(req->getParameter("end_date"));

    if (startPg.empty() || endPg.empty()) {
        cb(errResp("start_date and end_date must be MM/DD/YYYY", drogon::k400BadRequest));
        return;
    }

    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE transaction_datetime >= $1"
                     "   AND transaction_datetime <= $2"
                     " ORDER BY transaction_datetime");

    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) { cb(jsonResp(resultToArray(r))); },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        },
        startPg + " 00:00:00", endPg + " 23:59:59.999999"
    );
}

// ─── GET /api/v1/transactions/merchant?merchant= ─────────────────────────────

void TransactionController::getByMerchant(const drogon::HttpRequestPtr& req, Callback&& cb) {
    std::string merchant = req->getParameter("merchant");
    if (merchant.empty()) {
        cb(errResp("merchant query param is required", drogon::k400BadRequest));
        return;
    }

    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE LOWER(place) LIKE LOWER('%' || $1 || '%')"
                     " ORDER BY transaction_datetime");

    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) { cb(jsonResp(resultToArray(r))); },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        },
        merchant
    );
}

// ─── GET /api/v1/transactions/amount_range?amount_start=&amount_end= ─────────

void TransactionController::getByAmtRange(const drogon::HttpRequestPtr& req, Callback&& cb) {
    std::string startStr = req->getParameter("amount_start");
    std::string endStr   = req->getParameter("amount_end");

    if (startStr.empty() || endStr.empty()) {
        cb(errResp("amount_start and amount_end query params are required", drogon::k400BadRequest));
        return;
    }

    double amountStart = 0.0, amountEnd = 0.0;
    try {
        amountStart = std::stod(startStr);
        amountEnd   = std::stod(endStr);
    } catch (...) {
        cb(errResp("amount_start and amount_end must be numeric", drogon::k400BadRequest));
        return;
    }

    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions"
                     " WHERE amount >= $1 AND amount <= $2"
                     " ORDER BY transaction_datetime");

    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) { cb(jsonResp(resultToArray(r))); },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        },
        amountStart, amountEnd
    );
}

// ─── POST /api/v1/transactions ────────────────────────────────────────────────

void TransactionController::create(const drogon::HttpRequestPtr& req, Callback&& cb) {
    auto body = req->getJsonObject();
    if (!body) {
        cb(errResp("Invalid or missing JSON body", drogon::k400BadRequest));
        return;
    }

    for (const char* field : {"transaction_datetime", "amount", "transaction_type"}) {
        if (!body->isMember(field)) {
            cb(errResp(std::string("Missing required field: ") + field,
                       drogon::k422UnprocessableEntity));
            return;
        }
    }

    std::string dt    = (*body)["transaction_datetime"].asString();
    double   amount   = (*body)["amount"].asDouble();
    std::string place = body->isMember("place") ? (*body)["place"].asString() : "";
    std::string type  = (*body)["transaction_type"].asString();

    std::string sql =
        std::string(AY_OBFUSCATE(
            "INSERT INTO transactions"
            " (transaction_datetime, amount, place, transaction_type)"
            " VALUES ($1::timestamptz, $2, $3, $4)"
            " RETURNING "))
        + selectCols();

    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) {
            cb(jsonResp(rowToJson(r[0]), drogon::k201Created));
        },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        },
        dt, amount, place, type
    );
}

// ─── GET /api/v1/transactions/{id} ───────────────────────────────────────────

void TransactionController::getById(const drogon::HttpRequestPtr&, Callback&& cb, int id) {
    std::string sql =
        std::string(AY_OBFUSCATE("SELECT ")) + selectCols() +
        AY_OBFUSCATE(" FROM transactions WHERE transaction_id = $1");

    drogon::app().getDbClient()->execSqlAsync(
        sql,
        [cb](const drogon::orm::Result& r) {
            if (r.empty()) {
                cb(errResp("Transaction could not be found.", drogon::k404NotFound));
                return;
            }
            cb(jsonResp(rowToJson(r[0])));
        },
        [cb](const drogon::orm::DrogonDbException& e) {
            cb(errResp(e.base().what(), drogon::k500InternalServerError));
        },
        id
    );
}

// ─── PATCH /api/v1/transactions/{id} ─────────────────────────────────────────

void TransactionController::updateById(const drogon::HttpRequestPtr& req, Callback&& cb, int id) {
    auto body = req->getJsonObject();
    if (!body || body->empty()) {
        cb(errResp("Invalid or missing JSON body", drogon::k400BadRequest));
        return;
    }

    auto storage = std::make_shared<std::vector<std::string>>();
    std::string setClauses;
    int paramIdx = 1;

    auto addField = [&](const std::string& col, const std::string& value, bool isTimestamp = false) {
        if (!setClauses.empty()) setClauses += ", ";
        setClauses += col + " = $" + std::to_string(paramIdx++);
        if (isTimestamp) setClauses += "::timestamptz";
        storage->push_back(value);
    };

    if (body->isMember("transaction_datetime"))
        addField("transaction_datetime", (*body)["transaction_datetime"].asString(), true);
    if (body->isMember("amount"))
        addField("amount", std::to_string((*body)["amount"].asDouble()));
    if (body->isMember("place"))
        addField("place", (*body)["place"].asString());
    if (body->isMember("transaction_type"))
        addField("transaction_type", (*body)["transaction_type"].asString());

    if (setClauses.empty()) {
        cb(errResp("No updatable fields provided", drogon::k422UnprocessableEntity));
        return;
    }

    storage->push_back(std::to_string(id));

    std::string sql =
        std::string(AY_OBFUSCATE("UPDATE transactions SET ")) + setClauses +
        AY_OBFUSCATE(" WHERE transaction_id = $") + std::to_string(paramIdx) +
        AY_OBFUSCATE(" RETURNING ") + selectCols();

    auto binder = *drogon::app().getDbClient() << sql;
    for (const auto& s : *storage)
        binder << s;
    binder >> [cb, storage](const drogon::orm::Result& r) {
        if (r.empty()) {
            cb(errResp("Transaction could not be found.", drogon::k404NotFound));
            return;
        }
        cb(jsonResp(rowToJson(r[0])));
    };
    binder >> [cb, storage](const drogon::orm::DrogonDbException& e) {
        cb(errResp(e.base().what(), drogon::k500InternalServerError));
    };
}
