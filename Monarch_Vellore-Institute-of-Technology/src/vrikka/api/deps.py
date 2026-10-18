"""FastAPI dependencies: one Services instance per process and the bearer-token session."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vrikka.security import auth
from vrikka.services import Services

bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def services() -> Services:
    return Services()


def session(cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> auth.Session:
    s = auth.session_from_token(cred.credentials) if cred else None
    if s is None:
        raise HTTPException(status_code=401, detail="login required")
    return s
