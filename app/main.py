import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import demo, models
from .config import env
from .database import engine, get_db, make_engine
from .routers import ingest, insights, transactions


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not env.DEMO_SOURCE_DATABASE_NAME:
        models.Base.metadata.create_all(bind=engine)
        yield
        return

    # The public demo: serve a scrambled copy of the real database, kept fresh.
    source = make_engine(env.DEMO_SOURCE_DATABASE_NAME)
    demo.ensure_database(source, env.DATABASE_NAME)
    models.Base.metadata.create_all(bind=engine)
    refresher = asyncio.create_task(demo.keep_fresh(source, engine, env.INGEST_API_KEY))
    yield
    refresher.cancel()


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
app.include_router(insights.router)
# The demo's data comes from the real database, not from the Mac.
if not env.DEMO_SOURCE_DATABASE_NAME:
    app.include_router(ingest.router)


@app.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)):
    """For the container healthcheck: the API is up and can reach Postgres."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
