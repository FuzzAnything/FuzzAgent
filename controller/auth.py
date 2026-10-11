"""Token-based authentication for the FuzzAgent Controller API."""

import logging
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    api_token = request.app.state.config.api_token

    # api_token is None means auth is disabled (CONTROLLER_API_TOKEN env var not set)
    if api_token is None:
        return

    # api_token is empty string means auth is required but no token configured
    if api_token == "":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth is required but no API token is configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials is None:
        logger.warning("Auth failed: missing Authorization header from %s", request.client.host if request.client else "unknown")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, api_token):
        logger.warning("Auth failed: invalid token from %s", request.client.host if request.client else "unknown")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
