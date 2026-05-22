from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from decimal import Decimal

class Transaction(BaseModel):
    transaction_ID: int
    amount: Decimal
    place: str
    time: datetime
    transaction_type : Optional['str'] = None

