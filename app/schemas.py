from pydantic import AfterValidator, BaseModel, EmailStr, Field
from datetime import datetime
from typing import Annotated, Optional
from decimal import Decimal

from .config import env

def _assume_local_time(dt: datetime) -> datetime:
    """The client sends wall-clock times with no zone; read them as the app's zone."""
    return dt.replace(tzinfo=env.tz) if dt.tzinfo is None else dt

LocalDatetime = Annotated[datetime, AfterValidator(_assume_local_time)]

class Transaction(BaseModel):
    transaction_id: int
    amount: Optional[Decimal] = None
    place:  Optional[str] = None
    transaction_datetime: LocalDatetime
    transaction_type : str

class Date(BaseModel):
    date: str

class UpdateTransaction(BaseModel):
    transaction_id: int
    amount: Decimal | None = None
    place: str | None = None
    date: str
    transaction_datetime: LocalDatetime | None = None
    transaction_type: str | None = None

class SpendingDisplay(BaseModel):
    daily: Decimal
    weekly: Decimal
    rolling: Decimal
    monthly: Decimal

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
