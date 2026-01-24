from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"{name} is required")
    return value


# PUBLIC_INTERFACE
def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


# PUBLIC_INTERFACE
def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    return pwd_context.verify(password, password_hash)


# PUBLIC_INTERFACE
def create_access_token(subject: str, is_admin: bool, expires_in_minutes: int) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: Unique identifier for the principal (e.g., email).
        is_admin: Whether the principal has admin privileges.
        expires_in_minutes: Expiration window.

    Returns:
        Signed JWT string.
    """
    secret = _get_env("JWT_SECRET")
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=int(expires_in_minutes))

    payload: Dict[str, Any] = {
        "sub": subject,
        "is_admin": bool(is_admin),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


# PUBLIC_INTERFACE
def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Raises:
        HTTPException(401) if invalid/expired.
    """
    secret = _get_env("JWT_SECRET")
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        if not payload.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from e
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e
