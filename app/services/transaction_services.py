import base64
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import env
from ..sms_parser import parseTransaction, transactionAnalysis

# A Credit Card Payment also produces a Withdrawal text for the same amount
# within this window. Only the payment is kept.
DEDUP_WINDOW = timedelta(seconds=60)


def local_today() -> date:
    """Today's date in the app's time zone, whatever zone the server runs in."""
    return datetime.now(env.tz).date()


def local_day_range(first: date, last: date | None = None) -> tuple[datetime, datetime]:
    """
    The span from the start of `first` to the start of the day after `last`
    (or after `first` alone), in the app's time zone. Filter with
    start <= t < end so a moment is never in two days.
    """
    last = last or first
    start = datetime.combine(first, time.min, env.tz)
    end = datetime.combine(last + timedelta(days=1), time.min, env.tz)
    return start, end


def parse_message(message: schemas.IngestMessage) -> dict:
    """Turns one raw RBC text into a transactions row."""
    body = base64.b64decode(message.body_b64) if message.body_b64 is not None else None

    # The parser was written against str() of the raw blob, so keep feeding it that.
    amount, place, transaction_type = transactionAnalysis(parseTransaction(str(body).upper()))

    return {
        "transaction_id": message.rowid,
        "transaction_datetime": datetime.fromtimestamp(message.sent_at, timezone.utc),
        "amount": Decimal(amount.replace(",", "")) if amount else None,
        "place": place,
        "transaction_type": transaction_type,
    }


def filter_cc_payment_duplicates(transactions, db: Session):
    """
    Remove Withdrawal entries that have a matching Credit Card Payment
    of the same amount within the dedup window. Checks within the batch
    first, then the DB (handles pairs that span two batches).
    """
    cc_payments = [
        (t['amount'], t['transaction_datetime'])
        for t in transactions
        if t['transaction_type'] == 'Credit Card Payment' and t['amount'] is not None
    ]

    filtered = []
    for t in transactions:
        if t['transaction_type'] == 'Withdrawal' and t['amount'] is not None:
            amount, dt = t['amount'], t['transaction_datetime']

            in_batch = any(
                amount == cc_amt and abs(dt - cc_dt) <= DEDUP_WINDOW
                for cc_amt, cc_dt in cc_payments
            )

            in_db = not in_batch and db.query(models.Transaction).filter(
                models.Transaction.transaction_type == 'Credit Card Payment',
                models.Transaction.amount == amount,
                models.Transaction.transaction_datetime.between(dt - DEDUP_WINDOW, dt + DEDUP_WINDOW),
            ).first() is not None

            if in_batch or in_db:
                continue

        filtered.append(t)
    return filtered


def delete_withdrawals_covered_by(payments, db: Session):
    """
    The other half of filter_cc_payment_duplicates: when the Withdrawal text
    arrived in an earlier batch than its Credit Card Payment, remove it now.
    """
    for p in payments:
        if p['transaction_type'] != 'Credit Card Payment' or p['amount'] is None:
            continue
        dt = p['transaction_datetime']
        db.query(models.Transaction).filter(
            models.Transaction.transaction_type == 'Withdrawal',
            models.Transaction.amount == p['amount'],
            models.Transaction.transaction_datetime.between(dt - DEDUP_WINDOW, dt + DEDUP_WINDOW),
        ).delete(synchronize_session=False)


def ingest_messages(db: Session, messages: list[schemas.IngestMessage]) -> int:
    """
    Parses, de-duplicates and stores a batch of texts. Safe to call again
    with texts already stored: those are skipped. Returns how many rows
    were inserted.
    """
    rows = filter_cc_payment_duplicates([parse_message(m) for m in messages], db)
    if not rows:
        return 0

    delete_withdrawals_covered_by(rows, db)
    inserted = db.execute(
        insert(models.Transaction)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["transaction_id"])
        .returning(models.Transaction.transaction_id)
    ).all()
    db.commit()
    return len(inserted)


def last_ingested_rowid(db: Session) -> int:
    """The highest chat.db ROWID stored so far, or 0 when there is none."""
    return max(db.query(func.max(models.Transaction.transaction_id)).scalar() or 0, 0)
