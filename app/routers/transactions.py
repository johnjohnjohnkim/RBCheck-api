from .. import models, schemas
from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from ..database import get_db
from typing import List
from datetime import datetime, time
from decimal import Decimal

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)

@router.get("/date", status_code=status.HTTP_200_OK, response_model = List[schemas.Transaction])
def send_date_transactions(date_str: str = None, db: Session = Depends(get_db)):

    # Defaults to current date if no date is provided
    if date_str is None:
        date_str = datetime.now().strftime('%m/%d/%Y')

    casted_date = datetime.strptime(date_str, '%m/%d/%Y').date()
    day_start = datetime.combine(casted_date, time.min)
    day_end = datetime.combine(casted_date, time.max)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime >= day_start, models.Transaction.transaction_datetime <= day_end).all()

    return results


@router.post("", status_code = status.HTTP_201_CREATED, response_model=schemas.Transaction)
def send_transaction(transactions: schemas.Transaction, db: Session = Depends(get_db)):
    new_transaction = models.Transaction(**transactions.model_dump())

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    return new_transaction
    

@router.patch("/{id}", response_model=schemas.Transaction, status_code=status.HTTP_200_OK)
def update_transaction(id: int, updated_input: schemas. UpdateTransaction, db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.transaction_id == id).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction could not be found.")

    updated_transaction = updated_input.model_dump(exclude_unset=True)

    for key, value in updated_transaction.items():
        setattr(transaction, key, value)

    db.commit()
    db.refresh(transaction)
    return transaction

@router.get("/weekly", response_model=List[schemas.Transaction])
def current_week_transactions():
    pass

@router.get("/past_7_days", response_model=List[schemas.Transaction])
def past_7_days_transactions():
    pass

@router.get("/monthly", response_model=List[schemas.Transaction])
def current_month_transactions():
    pass

@router.get("/biweekly", response_model=List[schemas.Transaction])
def biweekly_transactions():
    pass

@router.get("/date_range", response_model=List[schemas.Transaction])
def transactions_by_date_range(start_date: str, end_date: str, db: Session = Depends(get_db)):
    pass

def transactions_at_merchant(merchant: str, db: Session = Depends(get_db)):
    pass

def transaction_amount_range(amount_start: Decimal, amount_end: Decimal, Session = Depends(get_db)):
    pass

@router.get("/{id}", status_code = status.HTTP_200_OK, response_model=schemas.Transaction)
def get_one_transaction(id: int, db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.transaction_id == id).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction could not be found.")
    
    return transaction
