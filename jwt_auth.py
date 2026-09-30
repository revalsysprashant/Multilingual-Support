"""
JWT-based login sessions.

A signed JWT is issued the moment someone logs in or signs up, and verified on
every protected request afterward. The token itself is stored in an httpOnly
cookie — NOT localStorage. That distinction matters: localStorage is readable
by any JavaScript running on the page, so if the site ever had an XSS bug,
malicious script could steal the token directly. An httpOnly cookie is invisible
to JavaScript entirely; only the browser attaches it automatically to requests.

What's inside the token (the "claims"):
  sub — the username this token belongs to ("subject")
  iat — when it was issued
  exp — when it expires, independent of how long the cookie itself survives
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, HTTPException

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET

COOKIE_NAME = 'access_token'


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'sub': username,
        'iat': now,
        'exp': now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Returns the username if the token is valid and not expired, otherwise None.
    Deliberately never raises — callers just treat None as 'not logged in'."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('sub')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_auth(access_token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    """FastAPI dependency — add `username: str = Depends(require_auth)` to any
    route that should only work for a logged-in user. Raises 401 otherwise."""
    if not access_token:
        raise HTTPException(status_code=401, detail='Not logged in')
    username = decode_access_token(access_token)
    if not username:
        raise HTTPException(status_code=401, detail='Session expired or invalid — please log in again')
    return username