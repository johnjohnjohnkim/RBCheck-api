from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models
from .database import engine
from .routers import auth, ingest, transactions

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

origins = [
    "https://gwanwoo.dev",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https?://((localhost|127\.0\.0\.1)(:[0-9]+)?|([a-z0-9-]+\.)*gwanwoo\.dev)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(auth.router)
app.include_router(ingest.router)