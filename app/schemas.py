from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
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