#pragma once
#include <drogon/HttpController.h>

class TransactionController : public drogon::HttpController<TransactionController> {
public:
    METHOD_LIST_BEGIN
    // Static paths first so they win over the /{id} catch-all
    ADD_METHOD_TO(TransactionController::getByDate,     "/api/v1/transactions/date",         drogon::Get);
    ADD_METHOD_TO(TransactionController::getWeekly,     "/api/v1/transactions/weekly",       drogon::Get);
    ADD_METHOD_TO(TransactionController::getPast7Days,  "/api/v1/transactions/past_7_days",  drogon::Get);
    ADD_METHOD_TO(TransactionController::getMonthly,    "/api/v1/transactions/monthly",      drogon::Get);
    ADD_METHOD_TO(TransactionController::getBiweekly,   "/api/v1/transactions/biweekly",     drogon::Get);
    ADD_METHOD_TO(TransactionController::getDateRange,  "/api/v1/transactions/date_range",   drogon::Get);
    ADD_METHOD_TO(TransactionController::getByMerchant, "/api/v1/transactions/merchant",     drogon::Get);
    ADD_METHOD_TO(TransactionController::getByAmtRange, "/api/v1/transactions/amount_range", drogon::Get);
    // Collection + item routes
    ADD_METHOD_TO(TransactionController::create,        "/api/v1/transactions",              drogon::Post);
    ADD_METHOD_TO(TransactionController::getById,       "/api/v1/transactions/{id}",         drogon::Get);
    ADD_METHOD_TO(TransactionController::updateById,    "/api/v1/transactions/{id}",         drogon::Patch);
    METHOD_LIST_END

    using Callback = std::function<void(const drogon::HttpResponsePtr&)>;

    void getByDate    (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getWeekly    (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getPast7Days (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getMonthly   (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getBiweekly  (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getDateRange (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getByMerchant(const drogon::HttpRequestPtr& req, Callback&& cb);
    void getByAmtRange(const drogon::HttpRequestPtr& req, Callback&& cb);
    void create       (const drogon::HttpRequestPtr& req, Callback&& cb);
    void getById      (const drogon::HttpRequestPtr& req, Callback&& cb, int id);
    void updateById   (const drogon::HttpRequestPtr& req, Callback&& cb, int id);
};
