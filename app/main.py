from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models
from .database import engine, get_db
from .routers import auth, ingest, transactions


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

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


@app.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)):
    """For the container healthcheck: the API is up and can reach Postgres."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
