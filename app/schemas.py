from pydantic import AfterValidator, BaseModel, EmailStr, Field
from datetime import date, datetime
from typing import Annotated, Optional
from decimal import Decimal

from .config import env

def _assume_local_time(dt: datetime) -> datetime:
    """The client sends wall-clock times with no zone; read them as the app's zone."""
    return dt.replace(tzinfo=env.tz) if dt.tzinfo is None else dt

LocalDatetime = Annotated[datetime, AfterValidator(_assume_local_time)]

class NewTransaction(BaseModel):
    """A transaction entered by hand. The server picks its id."""
    amount: Optional[Decimal] = None
    place:  Optional[str] = None
    transaction_datetime: LocalDatetime
    transaction_type : str

class Transaction(NewTransaction):
    # Positive ids are chat.db ROWIDs; negative ids were entered by hand.
    transaction_id: int

class UpdateTransaction(BaseModel):
    amount: Decimal | None = None
    place: str | None = None
    transaction_datetime: LocalDatetime | None = None
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

class UserCreate(BaseModel):
    user_email: EmailStr
    user_password: str

class TokenData(BaseModel):
    id: Optional[int] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class IngestMessage(BaseModel):
    """One RBC text as the Mac agent reads it from chat.db."""
    rowid: int
    sent_at: int                    # Unix seconds, UTC
    body_b64: str | None = None     # message.attributedBody, base64; null when empty

class IngestBatch(BaseModel):
    messages: list[IngestMessage] = Field(max_length=1000)

class IngestResult(BaseModel):
    received: int
    inserted: int

class IngestCursor(BaseModel):
    last_rowid: int
