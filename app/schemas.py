from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from decimal import Decimal

class Transaction(BaseModel):
    transaction_id: int
    amount: Decimal
    place: str
    transaction_datetime: datetime
    transaction_type : Optional[str] = None

