from .. import models, schemas
from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from typing import List
from datetime import datetime, time, timedelta, date
from decimal import Decimal
from calendar import day_name
from fastapi import Query
from sqlalchemy.exc import DataError, IntegrityError
from ..services import clock
from ..services.insights import spending_summary
from ..services.transaction_services import build_datetime_range, insert_transaction

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)


def _parse_date(value: str, fmt: str) -> date:
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid date '{value}', expected format {fmt}.",
        )


def _out_of_range() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="A value is out of range (amounts are limited to 99,999,999.99).",
    )

@router.get("/summary", status_code=status.HTTP_200_OK, response_model=schemas.SpendingDisplay)
def sendSummary(db: Session = Depends(get_db)):
    return spending_summary(db, clock.today())

@router.get("/", status_code=status.HTTP_200_OK, response_model=List[schemas.Transaction])
def get_all_transactions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    return db.query(models.Transaction).order_by(models.Transaction.transaction_datetime.desc(), models.Transaction.transaction_id.desc()).offset(offset).limit(limit).all()


@router.get("/date", status_code=status.HTTP_200_OK, response_model = List[schemas.Transaction])
def send_date_transactions(date_str: str = "", db: Session = Depends(get_db)):

    # Defaults to current date if no date is provided
    if date_str == "":
        date_str = clock.today().strftime('%m/%d/%Y')

    casted_date = _parse_date(date_str, '%m/%d/%Y')
    day_max, day_min = build_datetime_range(casted_date)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime <= day_max, models.Transaction.transaction_datetime >= day_min).all()

    return results


@router.post("", status_code = status.HTTP_201_CREATED, response_model=schemas.Transaction)
def send_transaction(transactions: schemas.TransactionCreate, db: Session = Depends(get_db)):
    detail = (f"Transaction {transactions.transaction_id} already exists."
              if transactions.transaction_id is not None else "Could not allocate an id, try again.")
    conflict = HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    try:
        new_transaction = insert_transaction(db, transactions)
    except IntegrityError:
        db.rollback()
        raise conflict
    except DataError:
        db.rollback()
        raise _out_of_range()
    if new_transaction is None:
        raise conflict

    return new_transaction

@router.patch("/{id}", response_model=schemas.Transaction, status_code=status.HTTP_200_OK)
def update_transaction(id: int, updated_input: schemas.UpdateTransaction, db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.transaction_id == id).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction could not be found.")
     
    updated_transaction = updated_input.model_dump(exclude_unset=True, exclude_none=True)

    for key, value in updated_transaction.items():
        setattr(transaction, key, value)

    try:
        db.commit()
    except DataError:
        db.rollback()
        raise _out_of_range()
    db.refresh(transaction)
    return transaction

@router.get("/weekly", response_model=List[schemas.Transaction])
def current_week_transactions(db: Session = Depends(get_db)):
    # List of all transactions starting from Sunday or Monday, depending on User's preference?
    # can definitely just make it toggle it's no biggie

    # STARTING FROM MONDAY
    curr_date = clock.today()
    start = curr_date - timedelta(clock.today().weekday())

    day_max, day_min = build_datetime_range(curr_date, start)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()

    return results

@router.get("/past_7_days", response_model=List[schemas.Transaction])
def past_7_days_transactions(db: Session = Depends(get_db)):
    curr = clock.today()
    start = curr - timedelta(days=6)  # seven days including today

    day_max, day_min = build_datetime_range(curr, start)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()
    return results

@router.get("/month", response_model=List[schemas.Transaction])
def current_month_transactions(db: Session = Depends(get_db)):
    curr = clock.today()
    start = curr - timedelta(days=curr.day-1)

    day_max, day_min = build_datetime_range(curr, start)

    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()
    return results

@router.get("/date_range", response_model=List[schemas.Transaction])
def transactions_by_date_range(start_date: str, end_date: str = None, db: Session = Depends(get_db)):

    dt_start = _parse_date(start_date, '%Y-%m-%d')
    if end_date is None:
        end_date = clock.today()
    else:
        end_date = _parse_date(end_date, '%Y-%m-%d')

    day_max, day_min = build_datetime_range(dt_start, end_date)
    results = db.query(models.Transaction).filter(models.Transaction.transaction_datetime>= day_min, models.Transaction.transaction_datetime<=day_max).all()
    
    return results

@router.get("/merchant", response_model = List[schemas.Transaction])
def transactions_at_merchant(merchant: str, db: Session = Depends(get_db)):
    escaped = merchant.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    results = db.query(models.Transaction).filter(models.Transaction.place.ilike(f'%{escaped}%', escape="\\")).all()

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


