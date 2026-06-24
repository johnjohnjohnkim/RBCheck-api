#include "services/SmsParser.h"
#include <obfuscate.h>
#include <regex>
#include <algorithm>
#include <cctype>

namespace rbcheck {

std::string parseTransaction(const std::string& data) {
    auto findPos = [&](const char* marker) -> size_t {
        return data.find(marker);
    };

    size_t startPos = std::string::npos;

    if (auto pos = findPos(AY_OBFUSCATE("RBC: ")); pos != std::string::npos) {
        startPos = pos;
    } else if (auto pos = findPos(AY_OBFUSCATE("DEPOSIT")); pos != std::string::npos) {
        startPos = pos;
    } else if (findPos(AY_OBFUSCATE("AVAIL CREDIT")) != std::string::npos) {
        return "bw";
    }

    if (startPos == std::string::npos) return "";

    size_t endPos = data.find(AY_OBFUSCATE("HELP-TXT HELP"), startPos);
    if (endPos == std::string::npos) endPos = data.size();

    return data.substr(startPos, endPos - startPos);
}

std::tuple<std::string, std::string, std::string> transactionAnalysis(const std::string& text) {
    if (text == "bw") {
        return {"", "", std::string(AY_OBFUSCATE("Balance Warning!"))};
    }

    // Compiled once per process — static + AY_OBFUSCATE decrypts pattern on first call.
    static const std::regex amountRe(std::string(AY_OBFUSCATE(R"(\$([\d,]*\d))")));
    static const std::regex placeRe(std::string(AY_OBFUSCATE(R"(AT (.+?)(?:\. STOP-TXT| STOP-TXT))")));

    std::string amount;
    std::string place;
    std::string transactionType;

    std::smatch amountMatch;
    if (std::regex_search(text, amountMatch, amountRe)) {
        amount = amountMatch[1].str();
        amount.erase(std::remove(amount.begin(), amount.end(), ','), amount.end());
    }

    std::smatch placeMatch;
    if (std::regex_search(text, placeMatch, placeRe)) {
        place = placeMatch[1].str();
    }

    if (text.find(AY_OBFUSCATE("DEPOSIT")) != std::string::npos) {
        transactionType = AY_OBFUSCATE("Deposit");
    } else if (text.find(AY_OBFUSCATE("WITHDRAWAL")) != std::string::npos) {
        transactionType = AY_OBFUSCATE("Withdrawal");
    } else if (text.find(AY_OBFUSCATE("PURCHASE")) != std::string::npos) {
        transactionType = AY_OBFUSCATE("CC Purchase");
    } else if (text.find(AY_OBFUSCATE("PAYMENT OF")) != std::string::npos) {
        transactionType = AY_OBFUSCATE("Credit Card Payment");
    } else if (text.find(AY_OBFUSCATE("CREDITED FOR")) != std::string::npos) {
        transactionType = AY_OBFUSCATE("Credit Refund");
    }

    return {amount, place, transactionType};
}

} // namespace rbcheck
