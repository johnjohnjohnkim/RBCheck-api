#pragma once
#include <string>
#include <tuple>

namespace rbcheck {

// Extract RBC transaction text from raw attributedBody bytes.
// Returns "bw" for balance warning messages, empty string if no RBC content.
std::string parseTransaction(const std::string& data);

// Parse extracted SMS text into (amount_str, place, transaction_type).
// amount_str may be empty if no dollar amount is found.
std::tuple<std::string, std::string, std::string> transactionAnalysis(const std::string& text);

} // namespace rbcheck
