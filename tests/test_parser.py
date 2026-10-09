from app.sms_parser import parse_message

SUFFIX = b"\x86\x84\x01NSDictionary\x00\x00\x86\x84\x01i"


def blob(text: str) -> bytes:
    """Mimic an iMessage attributedBody: framing bytes around the message text."""
    return b"\x04\x0bstreamtyped\x81\xe8\x03NSString\x01\x94\x84+\x8f" + text.encode() + SUFFIX


def test_cc_purchase():
    result = parse_message(blob(
        "RBC: Purchase of $12.34 CAD from RBC Credit Card ************1234 made 07/04 "
        "at Example Cafe. STOP-TXT STOP/HELP-TXT HELP"
    ))
    assert result == {"amount": "12.34", "place": "EXAMPLE CAFE", "transaction_type": "CC Purchase"}


def test_amount_with_thousands_separator_has_no_comma():
    result = parse_message(blob(
        "RBC: Purchase of $1,234.56 CAD from RBC Credit Card ************1234 made 07/04 "
        "at Big Store. STOP-TXT STOP/HELP-TXT HELP"
    ))
    assert result["amount"] == "1234.56"


def test_deposit_has_no_rbc_prefix():
    result = parse_message(blob(
        "Deposit of $2,000.00 to RBC Acct TESTER   made 07/04. STOP-TXT STOP/HELP-TXT HELP"
    ))
    assert result["transaction_type"] == "Deposit"
    assert result["amount"] == "2000.00"
    assert result["place"] == ""


def test_withdrawal():
    result = parse_message(blob(
        "RBC: Withdrawal of $50.00 from RBC Acct TESTER   made 07/04. STOP-TXT STOP/HELP-TXT HELP"
    ))
    assert result["transaction_type"] == "Withdrawal"


def test_credit_card_payment():
    result = parse_message(blob(
        "RBC: Payment of $300.00 to RBC Credit Card ************1234 made 07/04. STOP-TXT STOP/HELP-TXT HELP."
    ))
    assert result["transaction_type"] == "Credit Card Payment"


def test_credit_refund():
    result = parse_message(blob(
        "RBC: RBC Credit Card ************1234 was credited for $9.99 CAD on 07/04 "
        "at WWW Store. STOP-TXT STOP/HELP-TXT HELP"
    ))
    assert result["transaction_type"] == "Credit Refund"
    assert result["place"] == "WWW STORE"


def test_message_without_help_footer_still_parses():
    result = parse_message(b"RBC: Purchase of $5.00 CAD made 07/04 at Shop. STOP-TXT")
    assert result == {"amount": "5.00", "place": "SHOP", "transaction_type": "CC Purchase"}


def test_balance_warning_is_ignored():
    assert parse_message(blob("Your avail credit is low.")) is None


def test_due_notice_is_not_a_transaction():
    assert parse_message(blob(
        "RBC: Credit card ************1234 is due 07/20. Min pymt: $25.00 CAD. STOP-TXT STOP/HELP-TXT HELP."
    )) is None


def test_unrelated_message_is_ignored():
    assert parse_message(blob("hey are you free tonight?")) is None
    assert parse_message(None) is None
