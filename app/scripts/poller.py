import time
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import litecursor
from ..routers.transactions import send_transaction
from ..sms_parser import parseTransaction, transactionAnalysis
from ..database import SessionLocal, litecursor
from .. import schemas
from ..import models

db = SessionLocal()

litequery = "SELECT MAX(m.ROWID) " \
"FROM message as m, handle as h " \
"WHERE h.id=72272 AND h.ROWID=m.handle_id"


while True:
    litecursor.execute(litequery)

    literesult = litecursor.fetchone()[0]
    pgresult = db.query(func.max(models.Transaction.transaction_id)).scalar()
    
    if pgresult != literesult:
        print("New transactions found!")

        lite_get_new_queries = "SELECT m.ROWID, datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime'), m.attributedBody " \
        "FROM message as m, handle as h " \
        f"WHERE h.id=72272 AND h.ROWID=m.handle_id AND m.ROWID > {pgresult} " \
        "ORDER BY m.date DESC;" 

        litecursor.execute(lite_get_new_queries)
        result = litecursor.fetchall()

        for trans in result:

            transaction = {}

            transaction["transaction_id"] = trans[0]
            transaction["transaction_datetime"] = trans[1]
            
            analysis = transactionAnalysis(parseTransaction(str(trans[2]).upper()))
            transaction["amount"] = analysis[0]
            transaction["place"] = analysis[1] 
            transaction["transaction_type"] = analysis[2]
            send_transaction(schemas.Transaction(**transaction), db)
    
    time.sleep(5)
    



        



