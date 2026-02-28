"""
JWT token creation and verification for Speech-to-Text Pipeline.

Tokens are issued via POST /auth/token (exchange API key → JWT).
Accepted in Authorization: Bearer <token> header on all protected endpoints.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import HTTPException, status

from common.config import settings
from common.logging_config import get_logger

logger = get_logger("api.jwt")

# Token type constant
TOKEN_TYPE = "bearer"


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: Token subject (typically the hashed API key or user identifier)
        expires_delta: Optional custom expiry; defaults to JWT_EXPIRE_MINUTES from config

    Returns:
        Encoded JWT string
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    logger.debug(f"Issued JWT for subject={subject[:8]}… expires={expire.isoformat()}")
    return token


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Args:
        token: Raw JWT string

    Returns:
        Decoded payload dict

    Raises:
        HTTPException 401 if token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access":
            raise JWTError("Wrong token type")
        return payload
    except JWTError as exc:
        logger.warning(f"JWT validation failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
