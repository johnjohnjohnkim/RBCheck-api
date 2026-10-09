from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import models
from .config import env
from .database import engine
from .routers import ingest, insights, transactions

from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    yield


# The interactive docs and schema list every endpoint, so they are opt-in.
docs = {} if env.ENABLE_DOCS else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(lifespan=lifespan, **docs)

# Only the configured site origins, no wildcards. Auth is a bearer token in a
# header, not a cookie, so credentials are not needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=env.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

MAX_BODY_BYTES = 1_000_000   # a 500-record batch is about 100 KB


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Refuse oversized bodies before they are read. Bodies sent without a
    Content-Length (chunked) are left to the reverse proxy's limit."""
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request body too large."}, status_code=413)
    return await call_next(request)


app.include_router(transactions.router)
app.include_router(insights.router)
app.include_router(ingest.router)


@app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
def healthz():
    """For load balancers and Docker health checks. Reveals nothing."""
    return {"status": "ok"}
