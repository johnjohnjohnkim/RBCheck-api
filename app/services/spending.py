from decimal import Decimal


def spend_value(transaction_type: str | None, amount) -> Decimal:
    """What a transaction contributes to spending. The one definition for the
    summary, the digests and (mirrored in js/app.js kindOf) the client.

    Card payments and deposits are money moving, not spending; refunds and
    credits subtract; everything else (purchases, withdrawals, manual entries)
    adds.
    """
    value = Decimal(str(amount)) if amount is not None else Decimal(0)
    kind = (transaction_type or "").lower()
    if "payment" in kind or "deposit" in kind:
        return Decimal(0)
    if "refund" in kind or "credit" in kind:
        return -value
    return value
