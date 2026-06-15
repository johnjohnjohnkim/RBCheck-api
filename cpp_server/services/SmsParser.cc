#include "services/SmsParser.h"
#include <regex>
#include <algorithm>
#include <cctype>

namespace rbcheck {

std::string parseTransaction(const std::string& data) {
    // Search for RBC message markers in raw binary/text data
    auto findPos = [&](const std::string& marker) -> size_t {
        return data.find(marker);
    };

    size_t startPos = std::string::npos;

    if (auto pos = findPos("RBC: "); pos != std::string::npos) {
        startPos = pos;
    } else if (auto pos = findPos("DEPOSIT"); pos != std::string::npos) {
        startPos = pos;
    } else if (findPos("AVAIL CREDIT") != std::string::npos) {
        return "bw";
    }

    if (startPos == std::string::npos) return "";

    // End marker matches Python: "HELP-TXT HELP"
    size_t endPos = data.find("HELP-TXT HELP", startPos);
    if (endPos == std::string::npos) endPos = data.size();

    return data.substr(startPos, endPos - startPos);
}

std::tuple<std::string, std::string, std::string> transactionAnalysis(const std::string& text) {
    std::string amount;
    std::string place;
    std::string transactionType;

    if (text == "bw") {
        return {"", "", "Balance Warning!"};
    }

    // Extract dollar amount: $X,XXX.XX
    std::regex amountRe(R"(\$([\d,]*\d))");
    std::smatch amountMatch;
    if (std::regex_search(text, amountMatch, amountRe)) {
        amount = amountMatch[1].str();
        amount.erase(std::remove(amount.begin(), amount.end(), ','), amount.end());
    }

    // Extract merchant: AT <place>. STOP-TXT or AT <place> STOP-TXT
    std::regex placeRe(R"(AT (.+?)(?:\. STOP-TXT| STOP-TXT))");
    std::smatch placeMatch;
    if (std::regex_search(text, placeMatch, placeRe)) {
        place = placeMatch[1].str();
    }

    // Determine transaction type — matches Python sms_parser.py order
    if (text.find("DEPOSIT") != std::string::npos) {
        transactionType = "Deposit";
    } else if (text.find("WITHDRAWAL") != std::string::npos) {
        transactionType = "Withdrawal";
    } else if (text.find("PURCHASE") != std::string::npos) {
        transactionType = "CC Purchase";
    } else if (text.find("PAYMENT OF") != std::string::npos) {
        transactionType = "Credit Card Payment";
    } else if (text.find("CREDITED FOR") != std::string::npos) {
        transactionType = "Credit Refund";
    }

    return {amount, place, transactionType};
}

} // namespace rbcheck
