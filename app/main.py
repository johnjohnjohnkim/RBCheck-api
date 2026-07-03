from fastapi import FastAPI, Response, status, HTTPException

from . import models
from .database import engine
from .routers import transactions

from contextlib import asynccontextmanager
from .database import conn
from fastapi.middleware.cors import CORSMiddleware


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    conn.close()