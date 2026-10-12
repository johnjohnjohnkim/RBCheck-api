"""
Endpoints for the Mac agent that forwards RBC texts from chat.db.
They take a shared key rather than a user login, and can only add data.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from .. import schemas
from ..config import env
from ..database import get_db
from ..services.transaction_services import ingest_messages, last_ingested_rowid

ingest_key_header = APIKeyHeader(name="X-Ingest-Key")

def require_ingest_key(key: str = Security(ingest_key_header)):
    if not secrets.compare_digest(key.encode(), env.INGEST_API_KEY.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ingest key")

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_ingest_key)],
)

@router.get("/cursor", response_model=schemas.IngestCursor)
def get_cursor(db: Session = Depends(get_db)):
    return schemas.IngestCursor(last_rowid=last_ingested_rowid(db))

@router.post("", response_model=schemas.IngestResult)
def ingest(batch: schemas.IngestBatch, db: Session = Depends(get_db)):
    inserted = ingest_messages(db, batch.messages)
    return schemas.IngestResult(received=len(batch.messages), inserted=inserted)
