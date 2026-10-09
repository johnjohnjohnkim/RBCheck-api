from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import require_read
from ..database import get_db
from ..services import clock
from ..services.insights import history, store_digest

router = APIRouter(prefix="/insights", tags=["insights"], dependencies=[Depends(require_read)])


@router.get("/today", response_model=schemas.Digest)
def todays_digest(db: Session = Depends(get_db)):
    # Always recomputed: today's numbers change as texts arrive.
    return store_digest(db, clock.today())


@router.get("/history", response_model=List[schemas.Digest])
def digest_history(days: int = Query(30, ge=1, le=366), db: Session = Depends(get_db)):
    return history(db, clock.today(), days)
