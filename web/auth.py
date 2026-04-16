import json
import os
from pathlib import Path
import bcrypt
from itsdangerous import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired

from web.config import SECRET_KEY, ALLOWED_EMAILS, SESSION_MAX_AGE


def get_users_db_path() -> Path:
    """Return the path to the users JSON database."""
    return Path(__file__).parent / 'users.json'


def init_users_db() -> None:
    """Initialize the users database file with an empty dict if it doesn't exist."""
    db_path = get_users_db_path()
    if not db_path.exists():
        with open(db_path, 'w') as f:
            json.dump({}, f)


def register_user(email: str, password: str) -> bool:
    """
    Register a new user with email and password.
    Password is hashed using bcrypt.
    Only emails in ALLOWED_EMAILS are allowed.
    Returns True on success, False if email not allowed or already registered.
    """
    if email not in ALLOWED_EMAILS:
        return False
    
    db_path = get_users_db_path()
    init_users_db()  # ensure file exists
    
    with open(db_path, 'r') as f:
        users = json.load(f)
    
    if email in users:
        return False  # already registered
    
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[email] = {"password_hash": password_hash}
    
    with open(db_path, 'w') as f:
        json.dump(users, f, indent=2)
    
    return True


def verify_user(email: str, password: str) -> bool:
    """
    Verify a user's email and password.
    Returns True if credentials are valid, False otherwise.
    """
    db_path = get_users_db_path()
    if not db_path.exists():
        return False
    
    with open(db_path, 'r') as f:
        users = json.load(f)
    
    if email not in users:
        return False
    
    stored_hash = users[email].get("password_hash")
    if not stored_hash:
        return False
    
    return bcrypt.checkpw(password.encode(), stored_hash.encode())


def create_session_token(email: str) -> str:
    """
    Create a signed session token for the given email.
    Uses URLSafeTimedSerializer with SECRET_KEY and SESSION_MAX_AGE.
    """
    serializer = URLSafeTimedSerializer(SECRET_KEY)
    return serializer.dumps(email)


def verify_session_token(token: str) -> str | None:
    """
    Verify a session token and return the email if valid.
    Returns None if token is expired or invalid.
    """
    serializer = URLSafeTimedSerializer(SECRET_KEY)
    try:
        email = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return email
    except (BadSignature, SignatureExpired):
        return None
