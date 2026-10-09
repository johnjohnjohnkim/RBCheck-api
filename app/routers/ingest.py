from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import require_write
from ..database import get_db
from ..services.ingestion import store_transactions
from ..services.transaction_services import get_ingest_cursor

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_write)])


@router.get("/cursor", response_model=schemas.IngestCursor)
def cursor(db: Session = Depends(get_db)):
    """Highest message id stored; the poller resumes after it."""
    return {"cursor": get_ingest_cursor(db)}


@router.post("/batch", response_model=schemas.IngestResult)
def batch(body: schemas.IngestBatch, db: Session = Depends(get_db)):
    return store_transactions(db, body.transactions)
