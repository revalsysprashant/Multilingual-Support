"""
Per-user chat history — one JSON file per user under data/history/, so each
account's conversation is private and persists across server restarts.
"""
import json
from pathlib import Path

from auth import safe_file_name

HISTORY_DIR = Path(__file__).parent / 'data' / 'history'
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def history_path(username: str) -> Path:
    return HISTORY_DIR / f"{safe_file_name(username)}.json"


def load_history(username: str) -> list:
    try:
        return json.loads(history_path(username).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(username: str, history: list):
    history_path(username).write_text(json.dumps(history, indent=2), encoding='utf-8')