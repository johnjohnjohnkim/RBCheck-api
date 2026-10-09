"""Bearer-token checks. Reads accept the read or write token; writes need the write token."""

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import env

_bearer = HTTPBearer(auto_error=False)


def _matches(presented: str, expected: str) -> bool:
    # compare_digest takes the same time wherever the strings first differ
    return hmac.compare_digest(presented.encode(), expected.encode())


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid token.",
                         headers={"WWW-Authenticate": "Bearer"})


def _token(credentials: HTTPAuthorizationCredentials | None) -> str:
    return credentials.credentials if credentials else ""


def require_read(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    token = _token(credentials)
    is_read, is_write = _matches(token, env.READ_TOKEN), _matches(token, env.WRITE_TOKEN)
    if not (is_read or is_write):
        raise _unauthorized()


def require_write(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    token = _token(credentials)
    is_read, is_write = _matches(token, env.READ_TOKEN), _matches(token, env.WRITE_TOKEN)
    if is_write:
        return
    if is_read:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This token is read-only.")
    raise _unauthorized()
