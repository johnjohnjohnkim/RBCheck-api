from sqlalchemy.orm import Session
from datetime import datetime, time, timedelta
from decimal import Decimal
from .. import models

def build_datetime_range(start_date, end_date=None):

    day_max = datetime.combine(start_date, time.max)
    if end_date is None:
        day_min = datetime.combine(start_date, time.min)
    else:
        day_min = datetime.combine(end_date, time.min)
    return day_max, day_min


def _parse_dt(dt):
    if isinstance(dt, str):
        return datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
    return dt


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