from fastapi import FastAPI, Response, status, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from random import randrange 
from typing import Optional




app = FastAPI()


transactions = [] # List taking in a dictionary of Date, Transaction Source and Amount



# with open("output.txt", "w") as f:
#     for i in range(len(transactions)):
#         print(transactions[i], file = f)

print("Log completed!")
