from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from src.auth.jwt import create_access_token, decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["Auth"])
security = HTTPBearer(auto_error=False)

# Simple in-memory user store (per spec: JWT auth required; persistence can be added later).
# NOTE: In production, store users in DB.
_USERS: dict[str, dict] = {}


class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="User email (acts as login identifier).")
    password: str = Field(..., min_length=8, description="User password (min 8 chars).")


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User email.")
    password: str = Field(..., description="User password.")


class AuthResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token.")
    token_type: str = Field("bearer", description="Token type (Bearer).")
    is_admin: bool = Field(..., description="Whether this principal is an admin.")


# PUBLIC_INTERFACE
def get_current_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    FastAPI dependency: validate Authorization: Bearer <token> and return principal payload.

    Returns:
        JWT payload dict with keys: sub, is_admin, iat, exp.
    """
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return decode_access_token(creds.credentials)


# PUBLIC_INTERFACE
def require_admin(principal: dict = Depends(get_current_principal)) -> dict:
    """FastAPI dependency: require is_admin=true."""
    if not principal.get("is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return principal


@router.post(
    "/register",
    summary="Register a user (JWT-based)",
    response_model=AuthResponse,
)
async def register(body: RegisterRequest) -> AuthResponse:
    """
    Register a user and return a JWT.

    Admin rule:
      - If ADMIN_EMAIL is set and matches the email, the user is treated as admin.
    """
    email = body.email.lower().strip()
    if email in _USERS:
        raise HTTPException(status_code=400, detail="User already exists")

    admin_email = (os.getenv("ADMIN_EMAIL") or "").lower().strip()
    is_admin = bool(admin_email and email == admin_email)

    _USERS[email] = {"password_hash": hash_password(body.password), "is_admin": is_admin}

    token = create_access_token(
        subject=email,
        is_admin=is_admin,
        expires_in_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "120")),
    )
    return AuthResponse(access_token=token, is_admin=is_admin)


@router.post(
    "/login",
    summary="Login (JWT-based)",
    response_model=AuthResponse,
)
async def login(body: LoginRequest) -> AuthResponse:
    """Login a user and return a JWT."""
    email = body.email.lower().strip()
    user = _USERS.get(email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(
        subject=email,
        is_admin=bool(user.get("is_admin")),
        expires_in_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "120")),
    )
    return AuthResponse(access_token=token, is_admin=bool(user.get("is_admin")))
