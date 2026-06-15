"""
A one-time use backfill python script to migrate a text message SQLite database <chat.db> to a detailed transaction postgres database
"""

from ..sms_parser import parseTransaction, transactionAnalysis
from ..database import litecursor
from ..routers.transactions import send_transaction
from ..database import SessionLocal
from ..services.transaction_services import filter_cc_payment_duplicates
from .. import schemas


query = "SELECT m.ROWID, datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime'), m.attributedBody " \
"FROM message as m, handle as h " \
"WHERE h.id=72272 AND h.ROWID=m.handle_id " \
"ORDER BY m.date DESC;" \

litecursor.execute(query)
result = litecursor.fetchall()

db = SessionLocal()

batch = []
for trans in result:
    analysis = transactionAnalysis(parseTransaction(str(trans[2]).upper()))
    batch.append({
        "transaction_id": trans[0],
        "transaction_datetime": trans[1],
        "amount": analysis[0],
        "place": analysis[1],
        "transaction_type": analysis[2],
    })

for transaction in filter_cc_payment_duplicates(batch):
    send_transaction(schemas.Transaction(**transaction), db)