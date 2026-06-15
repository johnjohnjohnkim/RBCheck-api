#pragma once
#include <string>
#include <optional>
#include <json/json.h>

namespace rbcheck {

struct Transaction {
    int         transaction_id       = 0;
    std::string transaction_datetime;
    double      amount               = 0.0;
    std::string place;
    std::string transaction_type;

    Json::Value toJson() const {
        Json::Value j;
        j["transaction_id"]       = transaction_id;
        j["transaction_datetime"] = transaction_datetime;
        j["amount"]               = amount;
        j["place"]                = place;
        j["transaction_type"]     = transaction_type;
        return j;
    }
};

struct TransactionCreate {
    std::string transaction_datetime;
    double      amount = 0.0;
    std::string place;
    std::string transaction_type;
};

struct TransactionUpdate {
    std::optional<std::string> transaction_datetime;
    std::optional<double>      amount;
    std::optional<std::string> place;
    std::optional<std::string> transaction_type;
};

} // namespace rbcheck
