from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from fastapi.security import HTTPAuthorizationCredentials

from ..auth import (
    extract_bearer_token,
    neon_bearer_scheme,
    verify_neon_auth_token,
)
from ..config import normalize_clan_tag
from ..db import (
    LastAccountError,
    activate_user_account,
    delete_user_account,
    list_user_accounts,
    update_user_account_clan,
    update_user_account_role,
    upsert_user_accounts,
)
from ..schemas import (
    ActivateAccountRequest,
    CommittedAccountsResponse,
    DeleteAccountResponse,
    ErrorResponse,
    LinkAccountItem,
    LinkAccountsRequest,
    ListAccountsResponse,
    UpdateAccountClanRequest,
    UpdateAccountRoleRequest,
)

router = APIRouter(
    prefix="/api/accounts",
    tags=["4. User Linked In-Game Accounts (user_ingame_accounts)"],
)


async def _resolve_account_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    query_user_id: str | None = None,
    body_user_id: str | None = None,
) -> str:
    """Resolve user_id from Neon Auth Bearer JWT or fallback to userId in query/body/header."""
    fallback_id = (
        query_user_id
        or body_user_id
        or request.query_params.get("userId")
        or request.query_params.get("user_id")
        or request.headers.get("X-User-Id")
        or ""
    ).strip()

    token = (
        credentials.credentials
        if credentials
        else extract_bearer_token(request.headers.get("Authorization"))
    )
    if token:
        try:
            user = await verify_neon_auth_token(token)
            return user["id"]
        except HTTPException:
            if fallback_id:
                return fallback_id
            raise

    if fallback_id:
        return fallback_id

    raise HTTPException(
        status_code=401,
        detail="Missing Authorization: Bearer <token> header or userId parameter",
    )


@router.get(
    "",
    summary="List Linked In-Game Accounts",
    description=(
        "Returns all in-game Clash of Clans player accounts (`player_tag`, `player_name`, "
        "`town_hall_level`, `clan_tag`, `clan_name`, `is_active`) linked to the authenticated online user."
    ),
    response_model=ListAccountsResponse,
    responses={401: {"model": ErrorResponse}},
)
async def route_list_accounts(
    request: Request,
    userId: str | None = Query(default=None, description="Optional userId fallback when not sending Bearer JWT"),
    user_id: str | None = Query(default=None, include_in_schema=False),
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    resolved_user_id = await _resolve_account_user_id(
        request, credentials, query_user_id=userId or user_id
    )
    accounts = await list_user_accounts(resolved_user_id)
    active_account = next(
        (a for a in accounts if a.get("is_active")),
        accounts[0] if accounts else None,
    )
    return {
        "items": accounts,
        "accounts": accounts,
        "activeAccount": active_account,
    }


@router.post(
    "",
    summary="Link In-Game Account(s) & Clan",
    description=(
        "Links one or more in-game players and their clan to the online user (used during "
        "Registration and in the \"Manage In-Game Accounts\" modal). Automatically sets the "
        "first linked player as `is_active = true`."
    ),
    response_model=CommittedAccountsResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def route_link_accounts(
    request: Request,
    payload: LinkAccountsRequest | list[LinkAccountItem] = Body(...),
    userId: str | None = Query(default=None, include_in_schema=False),
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    raw_items: list[dict[str, Any]] = []
    body_user_id: str | None = None

    if isinstance(payload, list):
        raw_items = [item.model_dump(exclude_none=True) for item in payload]
        if raw_items:
            body_user_id = raw_items[0].get("userId") or raw_items[0].get("user_id")
    else:
        body = payload.model_dump(exclude_none=True)
        body_user_id = payload.userId or payload.user_id or body.get("userId") or body.get("user_id")
        default_clan_tag = body.get("clanTag") or body.get("clan_tag")
        default_clan_name = body.get("clanName") or body.get("clan_name")
        default_badge_url = body.get("clanBadgeUrl") or body.get("clan_badge_url")

        batch = body.get("accounts") or body.get("players")
        if isinstance(batch, list) and batch:
            for entry in batch:
                item_dict = dict(entry) if isinstance(entry, dict) else {}
                if default_clan_tag and not (item_dict.get("clanTag") or item_dict.get("clan_tag")):
                    item_dict["clanTag"] = default_clan_tag
                if default_clan_name and not (item_dict.get("clanName") or item_dict.get("clan_name")):
                    item_dict["clanName"] = default_clan_name
                if default_badge_url and not (item_dict.get("clanBadgeUrl") or item_dict.get("clan_badge_url")):
                    item_dict["clanBadgeUrl"] = default_badge_url
                raw_items.append(item_dict)
        else:
            raw_items = [body]

    resolved_user_id = await _resolve_account_user_id(
        request, credentials, query_user_id=userId, body_user_id=body_user_id
    )

    try:
        accounts, txid = await upsert_user_accounts(resolved_user_id, raw_items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    active_account = next(
        (a for a in accounts if a.get("is_active")),
        accounts[0] if accounts else None,
    )
    return {
        "kind": "committed",
        "txid": txid,
        "account": active_account,
        "items": accounts,
        "accounts": accounts,
        "activeAccount": active_account,
    }


@router.patch(
    "/{playerTag}/activate",
    summary="Switch Active In-Game Player",
    description=(
        "Switches the online user's active in-game character in a single click so the app "
        "context and clan switcher reflect the selected player."
    ),
    response_model=CommittedAccountsResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def route_activate_account(
    request: Request,
    playerTag: str = Path(..., description="Player tag to activate (e.g. #P902L8Q or %23P902L8Q)", examples=["#P902L8Q"]),
    payload: ActivateAccountRequest | None = Body(default=None),
    userId: str | None = Query(default=None, include_in_schema=False),
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    body_user_id = None
    if payload is not None:
        raw = payload.model_dump(exclude_none=True)
        body_user_id = payload.userId or payload.user_id or raw.get("userId") or raw.get("user_id")

    resolved_user_id = await _resolve_account_user_id(
        request, credentials, query_user_id=userId, body_user_id=body_user_id
    )

    try:
        result = await activate_user_account(resolved_user_id, playerTag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Linked in-game account {normalize_clan_tag(playerTag)} not found for user",
        )

    active_account, accounts, txid = result
    return {
        "kind": "committed",
        "txid": txid,
        "account": active_account,
        "items": accounts,
        "accounts": accounts,
        "activeAccount": active_account,
    }


@router.patch(
    "/{playerTag}/clan",
    summary="Update In-Game Player's Clan",
    description="Changes the clan associated with a specific linked in-game player.",
    response_model=CommittedAccountsResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def route_update_account_clan(
    request: Request,
    playerTag: str = Path(..., description="Player tag (e.g. #P902L8Q or %23P902L8Q)", examples=["#P902L8Q"]),
    payload: UpdateAccountClanRequest = Body(...),
    userId: str | None = Query(default=None, include_in_schema=False),
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    body = payload.model_dump(exclude_none=True)
    body_user_id = payload.userId or payload.user_id or body.get("userId") or body.get("user_id")
    resolved_user_id = await _resolve_account_user_id(
        request, credentials, query_user_id=userId, body_user_id=body_user_id
    )

    clan_tag = payload.clanTag or payload.clan_tag or body.get("clanTag") or body.get("clan_tag")
    if not clan_tag or not str(clan_tag).strip():
        raise HTTPException(status_code=400, detail="clanTag is required")

    clan_name = payload.clanName or payload.clan_name or body.get("clanName") or body.get("clan_name")
    clan_badge_url = (
        payload.clanBadgeUrl
        or payload.clan_badge_url
        or body.get("clanBadgeUrl")
        or body.get("clan_badge_url")
    )

    try:
        result = await update_user_account_clan(
            resolved_user_id,
            playerTag,
            clan_tag=str(clan_tag),
            clan_name=str(clan_name) if clan_name else None,
            clan_badge_url=str(clan_badge_url) if clan_badge_url else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Linked in-game account {normalize_clan_tag(playerTag)} not found for user",
        )

    updated_account, accounts, txid = result
    active_account = next(
        (a for a in accounts if a.get("is_active")),
        accounts[0] if accounts else None,
    )
    return {
        "kind": "committed",
        "txid": txid,
        "account": updated_account,
        "items": accounts,
        "accounts": accounts,
        "activeAccount": active_account,
    }


@router.patch(
    "/{playerTag}/role",
    summary="Update In-Game Player's Clan Role",
    description=(
        "Updates the clan role (`\"member\"` vs `\"leader\"` / `\"coLeader\"` / `\"admin\"`) of a "
        "linked in-game player, determining whether the user views the CWL schedule in "
        "**Member (Read-Only)** mode or **Clan Admin (Editable)** mode."
    ),
    response_model=CommittedAccountsResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def route_update_account_role(
    request: Request,
    playerTag: str = Path(..., description="Player tag (e.g. #P902L8Q or %23P902L8Q)", examples=["#P902L8Q"]),
    payload: UpdateAccountRoleRequest = Body(...),
    userId: str | None = Query(default=None, include_in_schema=False),
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    body = payload.model_dump(exclude_none=True)
    body_user_id = payload.userId or payload.user_id or body.get("userId") or body.get("user_id")
    resolved_user_id = await _resolve_account_user_id(
        request, credentials, query_user_id=userId, body_user_id=body_user_id
    )

    role = payload.role or body.get("role")
    if not role or not str(role).strip():
        raise HTTPException(status_code=400, detail="role is required")

    try:
        result = await update_user_account_role(
            resolved_user_id,
            playerTag,
            role=str(role),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Linked in-game account {normalize_clan_tag(playerTag)} not found for user",
        )

    updated_account, accounts, txid = result
    active_account = next(
        (a for a in accounts if a.get("is_active")),
        accounts[0] if accounts else None,
    )
    return {
        "kind": "committed",
        "txid": txid,
        "account": updated_account,
        "items": accounts,
        "accounts": accounts,
        "activeAccount": active_account,
    }


@router.delete(
    "/{playerTag}",
    summary="Remove Linked In-Game Account",
    description=(
        "Removes a linked in-game player from the online user's profile, enforcing that the user "
        "cannot delete their last remaining in-game account (`total <= 1` returns HTTP 400)."
    ),
    response_model=DeleteAccountResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def route_delete_account(
    request: Request,
    playerTag: str = Path(..., description="Player tag to remove (e.g. #P902L8Q or %23P902L8Q)", examples=["#P902L8Q"]),
    payload: ActivateAccountRequest | None = Body(default=None),
    userId: str | None = Query(default=None, include_in_schema=False),
    credentials: HTTPAuthorizationCredentials | None = Depends(neon_bearer_scheme),
):
    body_user_id = None
    if payload is not None:
        raw = payload.model_dump(exclude_none=True)
        body_user_id = payload.userId or payload.user_id or raw.get("userId") or raw.get("user_id")

    resolved_user_id = await _resolve_account_user_id(
        request, credentials, query_user_id=userId, body_user_id=body_user_id
    )

    try:
        deleted = await delete_user_account(resolved_user_id, playerTag)
    except LastAccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Linked in-game account {normalize_clan_tag(playerTag)} not found for user",
        )

    return {
        "kind": "committed",
        "id": deleted["id"],
        "player_tag": deleted["player_tag"],
        "playerTag": deleted["playerTag"],
        "txid": deleted["txid"],
        "items": deleted["accounts"],
        "accounts": deleted["accounts"],
        "activeAccount": deleted["activeAccount"],
    }
