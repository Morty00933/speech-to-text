"""
Authentication for Speech-to-Text Pipeline.

Supports two authentication methods (accepted on all protected endpoints):
  1. API key  — X-API-Key: <plain-text-key>   (original method)
  2. JWT token — Authorization: Bearer <token>  (issued via POST /auth/token)

Either method is accepted; both verify against the same set of API keys.
"""
import hashlib
from typing import Optional
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from common.config import settings
from common.logging_config import get_logger

logger = get_logger("auth")

# Security scheme extractors
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Hash an API key for secure storage and comparison."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify API key from request header.

    Compares incoming key hash against:
    1. The primary key configured via API_KEY env variable.
    2. (Optional) Additional keys stored in API_KEYS env variable as
       comma-separated list of pre-hashed or plain keys.

    Args:
        api_key: API key from X-API-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    if not api_key:
        logger.warning("Missing API key in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    incoming_hash = hash_api_key(api_key)

    # Always verify via hash — no plaintext comparison to avoid timing leaks
    if incoming_hash == hash_api_key(settings.api_key):
        return api_key

    # Support multiple API keys via API_KEYS env var (comma-separated plain keys)
    extra_keys_raw = getattr(settings, "api_keys", "") or ""
    if extra_keys_raw:
        for extra_key in extra_keys_raw.split(","):
            extra_key = extra_key.strip()
            if extra_key and incoming_hash == hash_api_key(extra_key):
                return api_key

    logger.warning(f"Invalid API key attempt: {api_key[:8]}...")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def get_api_key_hash(api_key: str) -> str:
    """Return SHA-256 hash of the given API key.

    Call only with an already-verified key (i.e. after verify_api_key).
    Does NOT perform authentication — just hashes for DB lookup.
    """
    return hash_api_key(api_key)


def verify_token_or_api_key(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> str:
    """
    Universal authentication dependency.

    Accepts either:
      - X-API-Key: <plain-text-key>        (classic API key)
      - Authorization: Bearer <jwt-token>  (JWT issued via POST /auth/token)

    Returns the verified identifier (plain API key or JWT subject).
    Raises HTTP 401 if neither credential is present or both are invalid.
    """
    # --- Try JWT Bearer first ---
    if credentials is not None:
        from jwt_handler import decode_access_token
        payload = decode_access_token(credentials.credentials)
        # subject is the api_key_hash stored during token issuance
        subject = payload.get("sub", "")
        logger.debug(f"JWT auth OK for subject={subject[:12]}…")
        return subject  # Return the hash; callers that need the hash use this directly

    # --- Fall back to API key ---
    if api_key:
        return verify_api_key(api_key)

    logger.warning("No credentials provided (missing X-API-Key and Authorization header)")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or Authorization: Bearer <token>.",
        headers={"WWW-Authenticate": "Bearer"},
    )
