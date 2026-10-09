from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from .. import models, schemas
from .clock import app_tz

# transaction_id is a 32-bit INTEGER. Ids from MANUAL_ID_FLOOR up are reserved
# for manual entries. The poller cursor ignores that range so a manual entry
# can't make it skip real messages.
MANUAL_ID_FLOOR = schemas.MANUAL_ID_FLOOR


def build_datetime_range(start_date, end_date=None):
    """Returns (day_max, day_min). The two dates may be given in either order."""
    if end_date is None:
        end_date = start_date
    first, last = sorted((start_date, end_date))
    return datetime.combine(last, time.max), datetime.combine(first, time.min)


def _parse_dt(dt):
    if isinstance(dt, str):
        dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=app_tz())


def get_ingest_cursor(db: Session) -> int:
    """Highest iMessage ROWID already stored (manual entries excluded)."""
    return db.query(func.max(models.Transaction.transaction_id)).filter(
        models.Transaction.transaction_id < MANUAL_ID_FLOOR
    ).scalar() or 0


def next_manual_id(db: Session) -> int:
    highest = db.query(func.max(models.Transaction.transaction_id)).filter(
        models.Transaction.transaction_id >= MANUAL_ID_FLOOR
    ).scalar()
    return (highest or MANUAL_ID_FLOOR - 1) + 1


def insert_transaction(db: Session, transaction: schemas.TransactionCreate) -> models.Transaction | None:
    """Idempotent insert. Returns None if the id already exists.
    A transaction without an id gets the next id in the manual range."""
    data = transaction.model_dump()
    assigned = data["transaction_id"] is None
    for attempt in range(3):
        if assigned:
            data["transaction_id"] = next_manual_id(db)
        elif db.get(models.Transaction, data["transaction_id"]) is not None:
            return None
        row = models.Transaction(**data)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not assigned:
                return None  # someone else stored this id first
            if attempt == 2:
                raise
            continue  # two manual inserts picked the same id; pick again
        db.refresh(row)
        return row


def filter_cc_payment_duplicates(transactions, db=None):
    """
    Remove Withdrawal entries that have a matching Credit Card Payment
    of the same amount within 60 seconds. Checks within the batch first,
    then the DB (handles pairs that span two poll cycles).
    """
    cc_payments = [
        (Decimal(str(t['amount'])), _parse_dt(t['transaction_datetime']))
        for t in transactions
        if t['transaction_type'] == 'Credit Card Payment' and t['amount'] is not None
    ]

    filtered = []
    for t in transactions:
        if t['transaction_type'] == 'Withdrawal' and t['amount'] is not None:
            amount = Decimal(str(t['amount']))
            dt = _parse_dt(t['transaction_datetime'])

            in_batch = any(
                amount == cc_amt and abs((dt - cc_dt).total_seconds()) <= 60
                for cc_amt, cc_dt in cc_payments
            )

            in_db = False
            if db and not in_batch:
                lower = dt - timedelta(seconds=60)
                upper = dt + timedelta(seconds=60)
                in_db = db.query(models.Transaction).filter(
                    models.Transaction.transaction_type == 'Credit Card Payment',
                    models.Transaction.amount == amount,
                    models.Transaction.transaction_datetime.between(lower, upper),
                ).first() is not None

            if in_batch or in_db:
                continue

        filtered.append(t)
    return filtered


def transactions_between(db: Session, first: date, last: date) -> list[models.Transaction]:
    """All transactions on the calendar days first..last (inclusive), oldest first."""
    day_max, day_min = build_datetime_range(last, first)
    return db.query(models.Transaction).filter(
        models.Transaction.transaction_datetime >= day_min,
        models.Transaction.transaction_datetime <= day_max,
    ).order_by(models.Transaction.transaction_datetime, models.Transaction.transaction_id).all()
