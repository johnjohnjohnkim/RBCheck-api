"""
A one-time use backfill python script to migrate a text message SQLite database <chat.db> to a detailed transaction postgres database
"""

from fastapi import FastAPI, Response, status, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from random import randrange 
from sqlalchemy.orm import Session

from .sms_parser import parseTransaction, transactionAnalysis
from .database import litecursor

from .routers.transactions import send_transaction
from .database import SessionLocal
from . import schemas


query = "SELECT m.ROWID, datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime'), m.attributedBody " \
"FROM message as m, handle as h " \
"WHERE h.id=72272 AND h.ROWID=m.handle_id " \
"ORDER BY m.date DESC;" \

litecursor.execute(query)
result = litecursor.fetchall()

db = SessionLocal()

for trans in result:

    transaction = {}

    transaction["transaction_id"] = trans[0]
    transaction["transaction_datetime"] = trans[1]
    
    analysis = transactionAnalysis(parseTransaction(str(trans[2]).upper()))
    transaction["amount"] = analysis[0]
    transaction["place"] = analysis[1] 
    transaction["transaction_type"] = analysis[2]

    send_transaction(schemas.Transaction(**transaction), db)