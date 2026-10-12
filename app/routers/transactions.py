from .. import models, oauth2, schemas
from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from typing import List
from datetime import date, datetime, timedelta
from decimal import Decimal
from ..services.transaction_services import local_day_range, local_today

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(oauth2.get_current_user)],
)

def transactions_between(db: Session, start: datetime, end: datetime):
    return db.query(models.Transaction).filter(
        models.Transaction.transaction_datetime >= start,
        models.Transaction.transaction_datetime < end,
    ).order_by(models.Transaction.transaction_datetime.desc())

@router.get("/summary", status_code=status.HTTP_200_OK, response_model=schemas.SpendingDisplay)
def sendSummary(db: Session = Depends(get_db)):
    today = local_today()

    EXCLUDED_TYPES = ('Credit Card Payment', 'Deposit')

    def spent_since(first: date):
        start, end = local_day_range(first, today)
        result = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.transaction_datetime >= start,
            models.Transaction.transaction_datetime < end,
            models.Transaction.transaction_type.notin_(EXCLUDED_TYPES)
        ).scalar()
        return result or Decimal(0)

    return schemas.SpendingDisplay(
        daily=spent_since(today),
        weekly=spent_since(today - timedelta(days=today.weekday())),
        rolling=spent_since(today - timedelta(days=7)),
        monthly=spent_since(today.replace(day=1)),
    )

@router.get("/", status_code=status.HTTP_200_OK, response_model=List[schemas.Transaction])
def get_all_transactions(offset: int, limit: int, db: Session = Depends(get_db)):
    return db.query(models.Transaction).order_by(models.Transaction.transaction_datetime.desc()).offset(offset).limit(limit).all()


@router.get("/date", status_code=status.HTTP_200_OK, response_model=List[schemas.Transaction])
def send_date_transactions(date_str: str = "", db: Session = Depends(get_db)):

    # Defaults to current date if no date is provided
    try:
        day = datetime.strptime(date_str, '%m/%d/%Y').date() if date_str else local_today()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_str must be MM/DD/YYYY.")

    return transactions_between(db, *local_day_range(day)).all()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=schemas.Transaction)
def send_transaction(transactions: schemas.Transaction, db: Session = Depends(get_db)):
    new_transaction = models.Transaction(**transactions.model_dump())

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    return new_transaction

@router.patch("/{id}", response_model=schemas.Transaction, status_code=status.HTTP_200_OK)
def update_transaction(id: int, updated_input: schemas.UpdateTransaction, db: Session = Depends(get_db)):
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
def current_week_transactions(db: Session = Depends(get_db)):
    # STARTING FROM MONDAY
    today = local_today()
    monday = today - timedelta(days=today.weekday())

    return transactions_between(db, *local_day_range(monday, today)).all()

@router.get("/past_7_days", response_model=List[schemas.Transaction])
def past_7_days_transactions(db: Session = Depends(get_db)):
    today = local_today()

    return transactions_between(db, *local_day_range(today - timedelta(days=7), today)).all()

@router.get("/month", response_model=List[schemas.Transaction])
def current_month_transactions(db: Session = Depends(get_db)):
    today = local_today()

    return transactions_between(db, *local_day_range(today.replace(day=1), today)).all()

@router.get("/date_range", response_model=List[schemas.Transaction])
def transactions_by_date_range(start_date: date, end_date: date | None = None, db: Session = Depends(get_db)):
    end_date = end_date or local_today()
    first, last = sorted((start_date, end_date))

    return transactions_between(db, *local_day_range(first, last)).all()

@router.get("/merchant", response_model=List[schemas.Transaction])
def transactions_at_merchant(merchant: str, db: Session = Depends(get_db)):
    results = db.query(models.Transaction).filter(models.Transaction.place.ilike(f'%{merchant}%')).all()

    return results
    
@router.get("/price_range", response_model=List[schemas.Transaction]) 
def transaction_amount_range(range_start: Decimal, range_end: Decimal, db: Session = Depends(get_db)):
    max_amount = max(range_start, range_end)
    min_amount = min(range_start, range_end)
    results = db.query(models.Transaction).filter(models.Transaction.amount >= min_amount, models.Transaction.amount <= max_amount).all()
    
    return results

@router.get("/{id}", status_code=status.HTTP_200_OK, response_model=schemas.Transaction)
def get_one_transaction(id: int, db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.transaction_id == id).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction could not be found.")
    
    return transaction
