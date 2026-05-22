from .. import models, schemas
from fastapi import Response, status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from ..database import get_db
from typing import List

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)

@router.post("", status_code = status.HTTP_201_CREATED, response_model=schemas.Transaction)
def send_transaction(transactions: schemas.Transaction, db: Session = Depends(get_db)):
    new_transaction = models.Transaction(**transactions.model_dump())

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    return new_transaction
    

@router.put("/{id}", response_model=schemas.Transaction)
def update_transaction(id: int, db: Session = Depends(get_db)):
    pass