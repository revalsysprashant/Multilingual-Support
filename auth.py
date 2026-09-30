"""
User accounts: signup/login storage (a plain JSON file), password hashing with
bcrypt, and the FastAPI dependency (require_auth) that other routes use to
check "is this request from a logged-in user?"
"""
import json
import re
from pathlib import Path

import bcrypt
from fastapi import HTTPException, Request

DATA_DIR = Path(__file__).parent / 'data'
USERS_FILE = DATA_DIR / 'users.json'
DATA_DIR.mkdir(parents=True, exist_ok=True)

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_]{3,32}$')


def is_valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username))


def is_valid_password(password: str) -> bool:
    return len(password) >= 6


def load_users() -> dict:
    try:
        return json.loads(USERS_FILE.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding='utf-8')


def safe_username_key(username: str) -> str:
    """Lowercased, trimmed — how usernames are looked up (case-insensitive)."""
    return username.strip().lower()


def safe_file_name(username: str) -> str:
    """Sanitized for use as a filename (per-user history file), e.g. 'kishore' -> 'kishore'."""
    return re.sub(r'[^a-z0-9_-]', '_', safe_username_key(username))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def require_auth(request: Request) -> str:
    """FastAPI dependency — add `username: str = Depends(require_auth)` to any
    route that should only work for a logged-in user. Raises 401 otherwise."""
    username = request.session.get('username')
    if not username:
        raise HTTPException(status_code=401, detail='Not logged in')
    return username