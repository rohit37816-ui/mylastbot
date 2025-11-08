import bcrypt
import json
from pathlib import Path
from datetime import datetime

USERS_FILE = Path("users.json")

def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def verify_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def load_users() -> dict:
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

def register_user(username: str, password: str) -> bool:
    users = load_users()
    if username in users:
        return False  # User already exists
    hashed = hash_password(password).decode('utf-8')
    users[username] = {
        "password": hashed,
        "created_at": datetime.utcnow().isoformat(),
        "settings": {}
    }
    save_users(users)
    return True

def authenticate_user(username: str, password: str) -> bool:
    users = load_users()
    user = users.get(username)
    if not user:
        return False
    hashed = user["password"].encode('utf-8')
    return verify_password(password, hashed)

