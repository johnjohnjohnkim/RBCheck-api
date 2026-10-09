"""Server side of the Mac -> API push: validate, de-duplicate and store parsed transactions."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from .. import models, schemas
from .clock import app_tz
from .transaction_services import MANUAL_ID_FLOOR, filter_cc_payment_duplicates, insert_transaction

SETTLEMENT_WINDOW = timedelta(seconds=60)


def _wall_clock(dt: datetime) -> datetime:
    """Comparable local time: aware values are converted to the app timezone, naive
    ones (SQLite) already are local."""
    return dt.astimezone(app_tz()).replace(tzinfo=None) if dt.tzinfo else dt


def _mark_settled_withdrawal(db: Session, amount: Decimal, when: datetime) -> int:
    """A card payment also shows up as a Withdrawal from the bank account. If that
    withdrawal arrived first it is already stored: mark the closest one for
    deletion. Nothing is committed here, so the deletion and the payment's insert
    land in one transaction: a crash can't leave both rows, and replaying a
    batch can't remove a second, genuine withdrawal.

    One payment removes at most one withdrawal, and manual entries are never touched."""
    candidates = db.query(models.Transaction).filter(
        models.Transaction.transaction_type == "Withdrawal",
        models.Transaction.amount == amount,
        models.Transaction.transaction_id < MANUAL_ID_FLOOR,
        models.Transaction.transaction_datetime.between(when - SETTLEMENT_WINDOW, when + SETTLEMENT_WINDOW),
    ).all()
    if not candidates:
        return 0
    closest = min(candidates, key=lambda w: abs(_wall_clock(w.transaction_datetime) - _wall_clock(when)))
    db.delete(closest)
    return 1


def _rejection(raw: Any, reason: str) -> dict:
    found = raw.get("transaction_id") if isinstance(raw, dict) else None
    return {"transaction_id": found if isinstance(found, int) and not isinstance(found, bool) else None,
            "reason": reason}


def store_transactions(db: Session, raw_items: list[Any]) -> dict:
    """Store a batch. Safe to repeat, including after a crash part-way through. A
    record that can never be stored is reported in `rejected` (and does not fail
    the batch); a database failure raises, so the sender retries the whole batch."""
    accepted, rejected = [], []
    for raw in raw_items:
        try:
            accepted.append(schemas.IngestItem(**raw).model_dump())
        except (ValidationError, TypeError):
            rejected.append(_rejection(raw, "invalid record"))

    stored = dropped = 0
    paired: set[int] = set()   # payments that already absorbed a withdrawal from this batch
    for item in filter_cc_payment_duplicates(accepted, db, paired):
        try:
            marked = 0
            if item["transaction_type"] == "Credit Card Payment" and item["transaction_id"] not in paired:
                marked = _mark_settled_withdrawal(db, item["amount"], item["transaction_datetime"])
            row = insert_transaction(db, schemas.Transaction(**item))   # commits the insert and the deletion together
            if row is None:
                db.rollback()   # already stored: it was handled before, so undo the pending deletion
                continue
            stored += 1
            dropped += marked
        except (DataError, OverflowError):
            db.rollback()
            rejected.append(_rejection(item, "value out of range"))
    return {"stored": stored, "dropped_withdrawals": dropped, "rejected": rejected}
