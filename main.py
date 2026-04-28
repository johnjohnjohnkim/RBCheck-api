import sqlite3
import os
import re

from fastapi import FastAPI, Response, status, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from random import randrange
from typing import Optional



def parseTransaction(text):
    '''
    Cheeky function finding where the embedded message within attributedBody starts and ends.
    Much easier to do this than parse through NSString (yuck)

    @returns string text of the transaction
    '''
    startPos = text.find("RBC: ")
    if startPos == -1:
        startPos = text.find("DEPOSIT")
    if startPos == -1:
        startPos = text.find("AVAIL CREDIT")
        return "bw"
    endPos = text.find("HELP-TXT HELP")

    return text[startPos:endPos]

def transactionAnalysis(text):
    transactionType = ""
    if text == "bw":
        transactionType = "Balance Warning!"
    amount = re.search('\\$[\\d.,]*\\d', text)
    amount = amount.group() if amount else "Null"

    place = re.search(r'AT (.+?)(?:\. STOP-TXT| STOP-TXT)', text)
    place = place.group(1) if place else ""

    if "DEPOSIT" in text:
        transactionType = "Deposit"
    elif "WITHDRAWAL" in text:
        transactionType = "Withdrawal"
    elif "PURCHASE" in text:
        transactionType = "CC Purchase"
    elif "PAYMENT OF" in text:
        transactionType = "Credit Card Payment"
    elif "CREDITED FOR" in text:
        transactionType = "Credit Refund"
    return amount, place, transactionType


transactions = [] # List taking in a dictionary of Date, Transaction Source and Amount

database = os.path.expanduser("~/Library/Messages/chat.db")

conn = sqlite3.connect(database)
cursor = conn.cursor()

query = "SELECT datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime'), m.attributedBody " \
"FROM message as m, handle as h " \
"WHERE h.id=72272 AND h.ROWID=m.handle_id " \
"ORDER BY m.date ASC;" \

cursor.execute(query)

result = cursor.fetchall()


for trans in result:
    transaction = {}
    
    transaction["Time"] = trans[0]
    analysis = transactionAnalysis(parseTransaction(str(trans[1]).upper()))

    transaction["Amount"] = analysis[0]
    transaction["Place"] = analysis[1] 
    transaction["Type"] = analysis[2]

    transactions.append(transaction)


with open("output.txt", "w") as f:
    for i in range(len(transactions)):
        print(transactions[i], file = f)
