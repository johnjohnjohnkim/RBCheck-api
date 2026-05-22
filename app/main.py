from fastapi import FastAPI, Response, status, HTTPException

from . import models
from .database import engine
from .routers import transactions

from contextlib import asynccontextmanager
from .database import conn

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(transactions.router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    conn.close()



### Unnecessary, will probably remove later if anything? ###

# with open("output.txt", "w") as f:
#     for i in range(len(transactions)):
#         print(transactions[i], file = f)

