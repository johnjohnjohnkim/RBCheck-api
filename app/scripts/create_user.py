"""
Creates a login, or sets a new password for an existing one. Sign-up is
closed, so this is the only way in. On the server:

    docker compose exec api python -m app.scripts.create_user you@example.com
"""

import getpass
import sys

from pydantic import ValidationError

from .. import models, schemas
from ..database import Base, SessionLocal, engine
from ..utils import hash as hash_password

MIN_PASSWORD_LENGTH = 12


def main():
    email = sys.argv[1] if len(sys.argv) > 1 else input("Email: ")
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Password again: "):
        sys.exit("Passwords don't match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Use at least {MIN_PASSWORD_LENGTH} characters.")

    try:
        user = schemas.UserCreate(user_email=email, user_password=password)
    except ValidationError:
        sys.exit(f"{email!r} isn't a valid email address.")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        existing = db.query(models.Users).filter(models.Users.user_email == user.user_email).first()
        if existing:
            existing.user_password = hash_password(password)
            print(f"Password updated for {user.user_email}.")
        else:
            db.add(models.Users(user_email=user.user_email, user_password=hash_password(password)))
            print(f"Created {user.user_email}.")
        db.commit()


if __name__ == "__main__":
    main()
