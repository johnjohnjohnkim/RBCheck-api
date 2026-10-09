from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional
from decimal import Decimal

# iMessage ROWIDs stay far below this; ids from here up are server-assigned manual entries.
MANUAL_ID_FLOOR = 10**9

class Transaction(BaseModel):
    transaction_id: int
    amount: Optional[Decimal] = None
    place:  Optional[str] = None
    transaction_datetime: datetime
    transaction_type : str

# Manual entries omit the id and the server assigns one (see insert_transaction).
# An explicit id is an iMessage ROWID, so it must stay below the manual range;
# that also keeps next_manual_id inside the 32-bit INTEGER column.
class TransactionCreate(Transaction):
    transaction_id: int | None = Field(default=None, ge=1, lt=MANUAL_ID_FLOOR)

class Date(BaseModel):
    date: str

# Partial update: unset fields are left alone; unknown fields (e.g. an old
# client's transaction_id/date) are ignored, so the primary key can't change.
class UpdateTransaction(BaseModel):
    amount: Decimal | None = None
    place: str | None = None
    transaction_datetime: datetime | None = None
    transaction_type: str | None = None

class SpendingDisplay(BaseModel):
    daily: Decimal
    weekly: Decimal
    rolling: Decimal
    monthly: Decimal

class DigestMerchant(BaseModel):
    name: str
    total: Decimal
    count: int

class DigestUnusual(BaseModel):
    transaction_id: int
    place: str
    amount: Decimal
    reason: str

class Digest(BaseModel):
    day: date
    spend: Decimal
    avg_previous_7: Decimal
    pct_vs_avg: float | None
    top_merchants: list[DigestMerchant]
    month_to_date: Decimal
    projected_month_end: Decimal | None   # null until enough days have completed
    final: bool                           # false while the day is still in progress
    purchase_count: int
    unusual: list[DigestUnusual]
    computed_at: datetime


# What the Mac sends. Stricter than Transaction: a real iMessage id, a known type
# and a positive amount that fits the column, so a bad record is rejected on its
# own instead of failing the whole batch.
class IngestItem(Transaction):
    transaction_id: int = Field(ge=1, lt=MANUAL_ID_FLOOR)
    transaction_type: Literal["CC Purchase", "Withdrawal", "Deposit", "Credit Card Payment", "Credit Refund"]
    amount: Decimal = Field(gt=0, lt=10**8)

    @field_validator("transaction_datetime")
    @classmethod
    def _plausible_time(cls, value: datetime) -> datetime:
        # Rejects absurd years that would overflow date arithmetic downstream.
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not datetime(2000, 1, 1, tzinfo=timezone.utc) <= moment <= datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("transaction_datetime is outside the plausible range")
        return value

class IngestBatch(BaseModel):
    transactions: list[Any] = Field(max_length=500)

class IngestRejection(BaseModel):
    transaction_id: int | None
    reason: str

class IngestResult(BaseModel):
    stored: int
    dropped_withdrawals: int
    rejected: list[IngestRejection]

class IngestCursor(BaseModel):
    cursor: int
