import re


def extract_text(body) -> str:
    """Decode an iMessage attributedBody blob (or plain str) to upper-case text."""
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray, memoryview)):
        body = bytes(body).decode("utf-8", errors="ignore")
    return body.upper()


def parseTransaction(text: str) -> str | None:
    '''
    Finds where the embedded RBC message starts and ends inside the decoded
    attributedBody. Much easier than parsing NSString (yuck).

    @returns the transaction text, or None if the message is not a transaction
    (this includes balance warnings, which are deliberately not stored).
    '''
    startPos = text.find("RBC: ")
    if startPos == -1:
        startPos = text.find("DEPOSIT")
    if startPos == -1:
        return None

    endPos = text.find("HELP-TXT HELP")
    return text[startPos:] if endPos == -1 else text[startPos:endPos]


def transactionAnalysis(text: str) -> tuple[str | None, str, str | None]:
    '''
    @returns (amount, place, transaction_type). transaction_type is None for
    messages that are not transactions (e.g. "credit card is due" notices).
    '''
    amount = re.search(r'\$([\d.,]*\d)', text)
    amount = amount.group(1).replace(",", "") if amount else None

    place = re.search(r'\bAT (.+?)(?:\. STOP-TXT| STOP-TXT)', text)
    place = place.group(1) if place else ""

    transactionType = None
    if "DEPOSIT" in text:
        transactionType = "Deposit"
    elif "WITHDRAWAL" in text:
        transactionType = "Withdrawal"
    elif "PURCHASE" in text:
        transactionType = "CC Purchase"
    elif "PAYMENT OF" in text:
        transactionType = "Credit Card Payment"
    elif "CREDITED FOR" in text:
        transactionType = "Credit Refund"
    return amount, place, transactionType


def parse_message(body) -> dict | None:
    """Full pipeline for one raw message body. None means 'not a transaction'."""
    text = parseTransaction(extract_text(body))
    if text is None:
        return None
    amount, place, transaction_type = transactionAnalysis(text)
    if transaction_type is None:
        return None
    return {"amount": amount, "place": place, "transaction_type": transaction_type}
