from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db

router = APIRouter(
    tags=["auth"]
)

@router.post("/login", response_model=schemas.Token)
def login(credentials: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    invalid_credentials = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")

    user = db.query(models.Users).filter(models.Users.user_email == credentials.username).first()
    if not user or not utils.verify(credentials.password, user.user_password):
        raise invalid_credentials

    access_token = oauth2.create_token(data={"user_id": user.user_id})
    return schemas.Token(access_token=access_token, token_type="bearer")
