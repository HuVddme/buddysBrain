import os
from secrets import compare_digest

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config  # noqa: F401

bearer = HTTPBearer(auto_error=False)


def require_resource_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    expected = os.getenv("RESOURCE_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Resource administration is not configured.")
    if credentials is None or not compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            401, "Administrator credentials required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
