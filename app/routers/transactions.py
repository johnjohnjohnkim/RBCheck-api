from .. import models, schemas
from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from typing import List
from datetime import datetime, time, timedelta, date
from decimal import Decimal
from calendar import day_name
from ..services.transaction_services import build_datetime_range

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)

@router.get("/summary", status_code=status.HTTP_200_OK, response_model=schemas.SpendingDisplay)
def sendSummary(db: Session = Depends(get_db)):
    curr = date.today()

    EXCLUDED_TYPES = ('Credit Card Payment', 'Deposit')

    def query_sum(day_max, day_min):
        result = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.transaction_datetime >= day_min,
            models.Transaction.transaction_datetime <= day_max,
            models.Transaction.transaction_type.notin_(EXCLUDED_TYPES)
        ).scalar()
        return result or Decimal(0)

    return schemas.SpendingDisplay(
        daily=query_sum(*build_datetime_range(curr)),
        weekly=query_sum(*build_datetime_range(curr, curr - timedelta(days=curr.weekday()))),
        rolling=query_sum(*build_datetime_range(curr, curr - timedelta(days=7))),
        monthly=query_sum(*build_datetime_range(curr, curr - timedelta(days=curr.day - 1))),
    )

@router.get("", status_code=status.HTTP_200_OK, response_model=List[schemas.Transaction])
def get_all_transactions(db: Session = Depends(get_db)):
    return db.query(models.Transaction).order_by(models.Transaction.transaction_datetime.desc()).all()


@router.get("/date", status_code=status.HTTP_200_OK, response_model = List[schemas.Transaction])
def send_date_transactions(date_str: str = "", db: Session = Depends(get_db)):

    # Defaults to current date if no date is provided
    if date_str == "":
        date_str = datetime.now().strftime('%m/%d/%Y')

    casted_date = datetime.strptime(date_str, '%m/%d/%Y').date()
    day_max, day_min = build_datetime_range(casted_date)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime <= day_max, models.Transaction.transaction_datetime >= day_min).all()

    return results


@router.post("", status_code = status.HTTP_201_CREATED, response_model=schemas.Transaction)
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
    # List of all transactions starting from Sunday or Monday, depending on User's preference?
    # can definitely just make it toggle it's no biggie

    # STARTING FROM MONDAY
    curr_date = date.today()
    start = curr_date - timedelta(date.today().weekday())

    day_max, day_min = build_datetime_range(curr_date, start)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()

    return results

@router.get("/past_7_days", response_model=List[schemas.Transaction])
def past_7_days_transactions(db: Session = Depends(get_db)):
    curr = date.today()
    start = curr - timedelta(days=7)

    day_max, day_min = build_datetime_range(curr, start)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()
    return results

@router.get("/month", response_model=List[schemas.Transaction])
def current_month_transactions(db: Session = Depends(get_db)):
    curr = date.today()
    start = curr - timedelta(days=curr.day-1)

    day_max, day_min = build_datetime_range(curr, start)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()
    return results

@router.get("/date_range", response_model=List[schemas.Transaction])
def transactions_by_date_range(start_date: str, end_date: str = None, db: Session = Depends(get_db)):

    dt_start = datetime.strptime(start_date, '%Y-%m-%d').date()
    if end_date is None:
        end_date = date.today()
    else: 
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

    day_max, day_min = build_datetime_range(dt_start, end_date)
    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()
    
    return results

@router.get("/merchant", response_model = List[schemas.Transaction])
def transactions_at_merchant(merchant: str, db: Session = Depends(get_db)):
    results = db.query(models.Transaction).filter(models.Transaction.place.ilike(f'%{merchant}%')).all()

    return results
    
@router.get("/price_range", response_model=List[schemas.Transaction]) 
def transaction_amount_range(range_start: Decimal, range_end: Decimal, db: Session = Depends(get_db)):
    max_amount = max(range_start, range_end)
    min_amount = min(range_start, range_end)
    results = db.query(models.Transaction).filter(models.Transaction.amount >= min_amount, models.Transaction.amount <= max_amount).all()
    
    return results

@router.get("/{id}", status_code = status.HTTP_200_OK, response_model=schemas.Transaction)
def get_one_transaction(id: int, db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.transaction_id == id).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction could not be found.")
    
    return transaction


