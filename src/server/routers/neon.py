from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from ..auth import (
    extract_bearer_token,
    fetch_jwks,
    neon_bearer_scheme,
    verify_neon_auth_token,
)
from ..config import (
    get_neon_auth_base_url,
    get_neon_auth_jwks_url,
    get_neon_realtime_url,
)
from ..db import check_db_status
from ..realtime import clan_league_live_query, seal_live_query
from ..schemas import NeonStatusResponse

router = APIRouter(
    prefix="/api/neon",
    tags=["3. Neon Realtime & Auth / System"],
)


@router.get(
    "/status",
    summary="Backend & Services Health Check",
    description=(
        "Verifies connectivity to Lakebase Postgres (`SELECT current_database(), now()`), "
        "validates the caller's Neon Auth JWT against `NEON_AUTH_JWKS_URL`, and verifies "
        "Neon Realtime query sealing."
    ),
    response_model=NeonStatusResponse,
)
async def route_neon_status(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    # 1. Verify Lakebase Postgres connectivity
    try:
        postgres_status = await check_db_status()
    except Exception as exc:
        postgres_status = {"connected": False, "error": str(exc)}

    # 2. Verify Neon Auth JWKS & optional caller Bearer token
    token = (
        credentials.credentials
        if credentials
        else extract_bearer_token(request.headers.get("Authorization"))
    )
    auth_status: dict[str, Any] = {
        "configured": bool(get_neon_auth_jwks_url()),
        "baseUrl": get_neon_auth_base_url(),
        "jwksUrl": get_neon_auth_jwks_url(),
        "authenticated": False,
        "user": None,
    }
    try:
        jwks = await fetch_jwks()
        auth_status["jwksReachable"] = True
        auth_status["keysCount"] = len(jwks.get("keys", []))
        if token:
            user = await verify_neon_auth_token(token)
            auth_status["authenticated"] = True
            auth_status["user"] = {
                "id": user["id"],
                "email": user.get("email"),
                "name": user.get("name"),
            }
    except HTTPException as exc:
        auth_status["tokenError"] = exc.detail
    except Exception as exc:
        auth_status["jwksReachable"] = False
        auth_status["error"] = str(exc)

    # 3. Verify Neon Realtime query sealing
    try:
        sample_sealed = seal_live_query(clan_league_live_query("#2PP"))
        realtime_status = {
            "configured": True,
            "sealed": True,
            "url": get_neon_realtime_url(),
            "queryFingerprint": sample_sealed["queryFingerprint"],
            "expiresAt": sample_sealed["expiresAt"],
        }
    except Exception as exc:
        realtime_status = {
            "configured": False,
            "sealed": False,
            "url": get_neon_realtime_url(),
            "error": str(exc),
        }

    overall_ok = bool(
        postgres_status.get("connected")
        and auth_status.get("jwksReachable")
        and realtime_status.get("sealed")
    )

    return {
        "ok": overall_ok,
        "postgres": postgres_status,
        "auth": auth_status,
        "realtime": realtime_status,
    }
