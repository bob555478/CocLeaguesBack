import time
from typing import Any
from urllib.parse import urlparse
import httpx
import jwt
from jwt import PyJWKSet
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_neon_auth_base_url, get_neon_auth_jwks_url

_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_TTL_SECONDS = 300.0

neon_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="NeonAuthBearer",
    description="Neon Auth (Managed Better Auth) JWT Bearer token",
)


async def fetch_jwks(jwks_url: str | None = None, force_refresh: bool = False) -> dict[str, Any]:
    url = jwks_url or get_neon_auth_jwks_url()
    if not url:
        raise RuntimeError("NEON_AUTH_JWKS_URL or NEON_AUTH_BASE_URL is not configured")

    now = time.monotonic()
    cached = _JWKS_CACHE.get(url)
    if cached and not force_refresh and (now - cached[0]) < _JWKS_TTL_SECONDS:
        return cached[1]

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        jwks_data = response.json()
        _JWKS_CACHE[url] = (now, jwks_data)
        return jwks_data


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1].strip()
        return token or None
    return None


async def verify_neon_auth_token(token: str) -> dict[str, Any]:
    """Verify a Neon Auth (Managed Better Auth) JWT against NEON_AUTH_JWKS_URL."""
    jwks_data = await fetch_jwks()
    jwk_set = PyJWKSet.from_dict(jwks_data)

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid JWT header: {exc}") from exc

    kid = unverified_header.get("kid")
    alg = unverified_header.get("alg") or "EdDSA"

    signing_key = None
    for jwk_key in jwk_set.keys:
        if kid is None or jwk_key.key_id == kid:
            signing_key = jwk_key.key
            break

    # Refresh JWKS once if kid wasn't found in cached keys
    if signing_key is None:
        jwks_data = await fetch_jwks(force_refresh=True)
        jwk_set = PyJWKSet.from_dict(jwks_data)
        for jwk_key in jwk_set.keys:
            if kid is None or jwk_key.key_id == kid:
                signing_key = jwk_key.key
                break

    if signing_key is None:
        raise HTTPException(status_code=401, detail="Matching JWK not found for token kid")

    auth_base_url = get_neon_auth_base_url()
    allowed_issuers: list[str] = []
    if auth_base_url:
        parsed = urlparse(auth_base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed_issuers = [origin, auth_base_url.rstrip("/"), auth_base_url]

    try:
        payload = jwt.decode(
            token,
            key=signing_key,
            algorithms=[alg, "EdDSA", "RS256", "ES256"],
            options={
                "verify_aud": False,
                "verify_iss": False,
                "require": ["exp", "sub"],
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired Neon Auth token: {exc}") from exc

    if allowed_issuers and payload.get("iss"):
        if payload["iss"] not in allowed_issuers:
            raise HTTPException(status_code=401, detail="Invalid token issuer")

    user_id = payload.get("sub") or payload.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token is missing user subject (sub)")

    return {
        "id": str(user_id),
        "email": payload.get("email"),
        "name": payload.get("name"),
        "claims": payload,
    }


async def verify_neon_auth_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency to require and verify a Neon Auth Bearer token (shows Authorize button in Swagger)."""
    token = credentials.credentials if credentials else extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token> header")
    return await verify_neon_auth_token(token)


# Alias matching the camelCase name referenced in API_ROUTES.md
verifyNeonAuthUser = verify_neon_auth_user
