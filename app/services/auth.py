import re
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.schemas import User

bearer_scheme = HTTPBearer(auto_error=False)
SAFE_SUBJECT = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")


@lru_cache(maxsize=4)
def cognito_jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True)


def _development_user(request: Request) -> User:
    subject = request.headers.get("X-Demo-User", "demo.researcher")
    if not SAFE_SUBJECT.fullmatch(subject):
        raise HTTPException(status_code=400, detail="Invalid demo user identifier")
    return User(subject=subject, email=f"{subject}@example.local", display_name="Demo Researcher")


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.environment == "development":
        return _development_user(request)
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    if not settings.cognito_user_pool_id or not settings.cognito_app_client_id:
        raise HTTPException(status_code=503, detail="Cognito is not configured")
    region = settings.cognito_user_pool_id.split("_")[0]
    issuer = f"https://cognito-idp.{region}.amazonaws.com/{settings.cognito_user_pool_id}"
    try:
        signing_key = cognito_jwks_client(issuer).get_signing_key_from_jwt(credentials.credentials)
        payload = jwt.decode(
            credentials.credentials,
            signing_key.key,
            audience=settings.cognito_app_client_id,
            issuer=issuer,
            algorithms=["RS256"],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid Cognito token") from exc
    subject = payload.get("sub")
    if payload.get("token_use") != "id":
        raise HTTPException(status_code=401, detail="Cognito ID token required")
    if not isinstance(subject, str) or not SAFE_SUBJECT.fullmatch(subject):
        raise HTTPException(status_code=401, detail="Token subject missing")
    return User(subject=subject, email=payload.get("email"), display_name=payload.get("given_name"))


CurrentUser = Annotated[User, Depends(current_user)]
