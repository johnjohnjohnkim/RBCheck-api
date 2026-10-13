from .. import models, oauth2, schemas
from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..database import get_db
from typing import List
from datetime import date, datetime, timedelta
from decimal import Decimal
from ..services import clock
from ..services.insights import spending_summary
from ..services.transaction_services import forget_digests_from, transactions_between

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(oauth2.get_current_user)],
)

@router.get("/summary", status_code=status.HTTP_200_OK, response_model=schemas.SpendingDisplay)
def sendSummary(db: Session = Depends(get_db)):
    return spending_summary(db, clock.today())

@router.get("/", status_code=status.HTTP_200_OK, response_model=List[schemas.Transaction])
def get_all_transactions(offset: int, limit: int, db: Session = Depends(get_db)):
    return db.query(models.Transaction).order_by(models.Transaction.transaction_datetime.desc()).offset(offset).limit(limit).all()


@router.get("/date", status_code=status.HTTP_200_OK, response_model=List[schemas.Transaction])
def send_date_transactions(date_str: str = "", db: Session = Depends(get_db)):

    # Defaults to current date if no date is provided
    try:
        day = datetime.strptime(date_str, '%m/%d/%Y').date() if date_str else clock.today()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="date_str must be MM/DD/YYYY.")

    return transactions_between(db, day).all()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=schemas.Transaction)
def send_transaction(transactions: schemas.NewTransaction, db: Session = Depends(get_db)):
    # Hand-entered rows count down from -1 so they never take a chat.db ROWID,
    # which the Mac agent will use later. The lock stops two at once picking the same id.
    db.execute(text("LOCK TABLE transactions IN SHARE ROW EXCLUSIVE MODE"))
    lowest = db.query(func.min(models.Transaction.transaction_id)).scalar() or 0
    new_transaction = models.Transaction(transaction_id=min(lowest, 0) - 1, **transactions.model_dump())

    db.add(new_transaction)
    forget_digests_from(db, [new_transaction.transaction_datetime])
    db.commit()
    db.refresh(new_transaction)

    return new_transaction

@router.patch("/{id}", response_model=schemas.Transaction, status_code=status.HTTP_200_OK)
def update_transaction(id: int, updated_input: schemas.UpdateTransaction, db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.transaction_id == id).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction could not be found.")
     
    updated_transaction = updated_input.model_dump(exclude_unset=True)
    was_at = transaction.transaction_datetime

    for key, value in updated_transaction.items():
        setattr(transaction, key, value)

    forget_digests_from(db, [was_at, transaction.transaction_datetime])
    db.commit()
    db.refresh(transaction)
    return transaction

@router.get("/weekly", response_model=List[schemas.Transaction])
def current_week_transactions(db: Session = Depends(get_db)):
    # STARTING FROM MONDAY
    today = clock.today()
    monday = today - timedelta(days=today.weekday())

    return transactions_between(db, monday, today).all()

@router.get("/past_7_days", response_model=List[schemas.Transaction])
def past_7_days_transactions(db: Session = Depends(get_db)):
    today = clock.today()

    return transactions_between(db, today - timedelta(days=7), today).all()

@router.get("/month", response_model=List[schemas.Transaction])
def current_month_transactions(db: Session = Depends(get_db)):
    today = clock.today()

    return transactions_between(db, today.replace(day=1), today).all()

@router.get("/date_range", response_model=List[schemas.Transaction])
def transactions_by_date_range(start_date: date, end_date: date | None = None, db: Session = Depends(get_db)):
    end_date = end_date or clock.today()
    first, last = sorted((start_date, end_date))

    return transactions_between(db, first, last).all()

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
