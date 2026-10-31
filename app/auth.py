"""Аутентификация: хеширование паролей, сессии, проверка прав."""
import hashlib
import secrets

from fastapi import Request, HTTPException, status

SESSIONS: dict[str, dict] = {}  # token -> {user_id, username, role}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() == h


def create_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user
    return token


def destroy_session(token: str | None):
    if token:
        SESSIONS.pop(token, None)


def get_session(request: Request) -> dict | None:
    token = request.cookies.get("session_token")
    return SESSIONS.get(token)


def require_role(request: Request, *roles: str) -> dict:
    """Возвращает сессию пользователя или бросает 401/403."""
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Требуется вход в систему")
    if roles and session["role"] not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Недостаточно прав")
    return session
