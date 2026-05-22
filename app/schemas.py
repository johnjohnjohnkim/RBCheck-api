from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from decimal import Decimal

class Transaction(BaseModel):
    transaction_id: int
    amount: Optional[Decimal] = None
    place:  Optional[str] = None
    transaction_datetime: datetime
    transaction_type : str
