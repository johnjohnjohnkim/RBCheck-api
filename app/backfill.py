"""
A one-time use backfill python script to migrate a text message SQLite database <chat.db> to a detailed transaction postgres database
"""

import fastapi
from fastapi import FastAPI, Response, status, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from random import randrange 
from psycopg.rows import dict_row
from sqlalchemy.orm import Session

from .transactions import parseTransaction, transactionAnalysis
from .database import litecursor


query = "SELECT m.ROWID, datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime'), m.attributedBody " \
"FROM message as m, handle as h " \
"WHERE h.id=72272 AND h.ROWID=m.handle_id " \
"ORDER BY m.date DESC;" \

litecursor.execute(query)
result = litecursor.fetchall()

for trans in result:

    transaction = {}

    transaction["rowID"] = trans[0]
    transaction["Time"] = trans[1]
    
    analysis = transactionAnalysis(parseTransaction(str(trans[1]).upper()))
    transaction["Amount"] = analysis[0]
    transaction["Place"] = analysis[1] 
    transaction["Type"] = analysis[2]

# parsedRows = []


# Order of backfill
# 1. Parse all transactions
# 2. Save each into a json format
# 3. 
