"""
Authentication routes — JWT token issuance.

POST /auth/token  — exchange a valid API key for a short-lived JWT.
The returned token can be used in the Authorization: Bearer <token> header
instead of X-API-Key on all protected endpoints.
"""
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from auth import verify_api_key, hash_api_key
from jwt_handler import create_access_token, TOKEN_TYPE
from common.config import settings
from common.logging_config import get_logger

logger = get_logger("api.routes.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])


class TokenRequest(BaseModel):
    """Request body for token issuance."""
    api_key: str = Field(..., description="Valid API key to exchange for a JWT token")


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str = Field(..., description="Signed JWT access token")
    token_type: str = Field(default=TOKEN_TYPE, description="Token type (always 'bearer')")
    expires_in: int = Field(..., description="Token lifetime in seconds")


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Exchange API key for JWT token",
    description=(
        "Submit a valid `X-API-Key` to receive a short-lived JWT access token. "
        "Use the token in subsequent requests as `Authorization: Bearer <token>`. "
        "Token lifetime is configurable via `JWT_EXPIRE_MINUTES` (default: 60 min)."
    ),
)
async def get_token(body: TokenRequest) -> TokenResponse:
    """Issue a JWT token in exchange for a valid API key."""
    # Reuse the existing API-key verification logic (raises 401 on failure)
    try:
        verify_api_key(body.api_key)
    except HTTPException:
        # Re-raise with a clearer message
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key — cannot issue token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Subject = hash of the API key (never store plain keys in JWTs)
    subject = hash_api_key(body.api_key)
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes)
    token = create_access_token(subject=subject, expires_delta=expires_delta)

    logger.info(f"Issued JWT token for key_hash={subject[:12]}…")

    return TokenResponse(
        access_token=token,
        token_type=TOKEN_TYPE,
        expires_in=int(expires_delta.total_seconds()),
    )
