from .. import models, schemas
from fastapi import status, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from ..database import get_db
from ..utils import hash as hash_password

router = APIRouter(
    prefix="/users",
    tags=["users"]
)

@router.post("", status_code=status.HTTP_201_CREATED, response_model=schemas.UserOut)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.Users).filter(models.Users.user_email == user.user_email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    new_user = models.Users(
        user_email=user.user_email,
        user_password=hash_password(user.user_password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
