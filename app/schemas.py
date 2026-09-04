from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from decimal import Decimal

class Transaction(BaseModel):
    transaction_id: int
    amount: Optional[Decimal] = None
    place:  Optional[str] = None
    transaction_datetime: datetime
    transaction_type : str

class Date(BaseModel):
    date: str

class UpdateTransaction(BaseModel):
    transaction_id: int
    amount: Decimal | None = None
    place: str | None = None
    date: str
    transaction_datetime: datetime | None = None
    transaction_type: str | None = None

class SpendingDisplay(BaseModel):
    daily: Decimal
    weekly: Decimal
    rolling: Decimal
    monthly: Decimal

class UserCreate(BaseModel):
    user_email: EmailStr
    user_password: str

class UserOut(BaseModel):
    user_id: int
    user_email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True

class TokenData(BaseModel):
    id: Optional[int] = None