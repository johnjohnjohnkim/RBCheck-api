from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated = "auto") #telling bcrypt what the default hashing algorithm is


def hash(password: str):
    return pwd_context.hash(password)

def verify(plain_pass, hashed_pass):
    return pwd_context.verify(plain_pass, hashed_pass)